from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from accounts.models import Organization, UserProfile
from employees.models import (
    Branch,
    Department,
    Designation,
    Employee,
)
from leave_management.models import (
    LeaveBalance,
    LeaveBalanceTransaction,
    LeavePolicy,
    LeavePolicyRule,
    LeavePolicyVersion,
    LeaveType,
)
from leave_management.accrual_services import accrue_monthly_leave


class MonthlyLeaveAccrualTests(TestCase):
    def setUp(self):
        self.organization = Organization.objects.create(
            name="Accrual Test Organization",
            code="ACCRTEST",
        )

        self.department = Department.objects.create(
            name="Accrual Test Department",
            code="ACCRDEPT",
        )

        self.other_department = Department.objects.create(
            name="Other Accrual Department",
            code="OTHERDEPT",
        )

        self.designation = Designation.objects.create(
            name="Accrual Test Designation",
            code="ACCRDES",
        )

        self.other_designation = Designation.objects.create(
            name="Other Accrual Designation",
            code="OTHERDES",
        )

        self.branch = Branch.objects.create(
            name="Accrual Test Branch",
            code="ACCRBR",
            state="Karnataka",
            city="Mysuru",
        )

        User = get_user_model()

        publisher_user = User.objects.create_user(
            username="accrual_policy_publisher",
            password="TestOnlyPassword123!",
        )

        self.publisher = UserProfile.objects.create(
            user=publisher_user,
            organization=self.organization,
            role=UserProfile.Role.SUPER_ADMIN,
        )

        self.leave_type = LeaveType.objects.create(
            organization=self.organization,
            code="CASUAL",
            name="Casual Leave",
        )

        self.employee = Employee.objects.create(
            organization=self.organization,
            first_name="Accrual",
            last_name="Employee",
            official_email="accrual.employee@example.com",
            registered_mobile="9876543210",
            joining_date=date(2026, 1, 1),
            probation_end_date=date(2026, 12, 31),
            employee_type="FULL_TIME",
            department=self.department,
            designation=self.designation,
            branch=self.branch,
            status=Employee.Status.ACTIVE,
        )

        self.accrual_date = date(2027, 3, 31)
        self.period_start = date(2027, 1, 1)
        self.period_end = date(2027, 12, 31)

        self.rule = self.create_rule()

    def create_rule(
        self,
        *,
        monthly_days="1.50",
        accrual_timing=LeavePolicyRule.AccrualTiming.MONTH_END,
        department=None,
        designation=None,
        employee_type="FULL_TIME",
        probation_condition=(
            LeavePolicyRule.ProbationCondition.ANY
        ),
        policy_active=True,
        rule_active=True,
    ):
        policy = LeavePolicy.objects.create(
            organization=self.organization,
            code=f"ACCRUAL{LeavePolicy.objects.count() + 1}",
            name="Accrual Test Policy",
            is_active=policy_active,
        )

        version = LeavePolicyVersion.objects.create(
            policy=policy,
            version_number=1,
            effective_from=date(2027, 1, 1),
        )

        rule = LeavePolicyRule.objects.create(
            version=version,
            leave_type=self.leave_type,
            department=department,
            designation=designation,
            employee_type=employee_type,
            probation_condition=probation_condition,
            monthly_accrual_days=Decimal(monthly_days),
            accrual_timing=accrual_timing,
            is_active=rule_active,
        )

        version.status = LeavePolicyVersion.Status.PUBLISHED
        version.published_by = self.publisher
        version.published_at = timezone.now()
        version.save()

        return rule

    def accrue(self, *, employee=None, rule=None, accrual_date=None):
        return accrue_monthly_leave(
            employee=employee or self.employee,
            rule=rule or self.rule,
            accrual_date=accrual_date or self.accrual_date,
            period_start=self.period_start,
            period_end=self.period_end,
        )

    def test_monthly_accrual_creates_balance_and_transaction(self):
        transaction = self.accrue()

        balance = LeaveBalance.objects.get(
            employee=self.employee,
            leave_type=self.leave_type,
        )

        self.assertEqual(
            balance.entitled_days,
            Decimal("1.50"),
        )

        self.assertEqual(
            transaction.transaction_type,
            LeaveBalanceTransaction.TransactionType.ACCRUAL,
        )

        self.assertEqual(
            transaction.days,
            Decimal("1.50"),
        )

        self.assertEqual(transaction.employee_id, self.employee.pk)
        self.assertEqual(transaction.policy_rule_id, self.rule.pk)

    def test_employee_without_login_account_can_receive_accrual(self):
        self.assertIsNone(self.employee.user)

        transaction = self.accrue()

        self.assertIsNotNone(transaction.pk)

    def test_repeated_accrual_does_not_duplicate_credit(self):
        first_transaction = self.accrue()
        second_transaction = self.accrue()

        self.assertEqual(
            first_transaction.pk,
            second_transaction.pk,
        )

        self.assertEqual(
            LeaveBalanceTransaction.objects.filter(
                employee=self.employee,
                transaction_type=(
                    LeaveBalanceTransaction.TransactionType.ACCRUAL
                ),
            ).count(),
            1,
        )

        balance = LeaveBalance.objects.get(
            employee=self.employee,
            leave_type=self.leave_type,
        )

        self.assertEqual(
            balance.entitled_days,
            Decimal("1.50"),
        )

    def test_inactive_employee_cannot_receive_accrual(self):
        self.employee.status = Employee.Status.DEACTIVATED
        self.employee.save(update_fields=["status"])

        with self.assertRaises(ValidationError):
            self.accrue()

        self.assertEqual(
            LeaveBalanceTransaction.objects.count(),
            0,
        )

    def test_department_mismatch_is_rejected(self):
        self.employee.department = self.other_department
        self.employee.save(update_fields=["department"])

        rule = self.create_rule(
            department=self.department,
        )

        with self.assertRaises(ValidationError):
            self.accrue(rule=rule)

    def test_designation_mismatch_is_rejected(self):
        self.employee.designation = self.other_designation
        self.employee.save(update_fields=["designation"])

        rule = self.create_rule(
            designation=self.designation,
        )

        with self.assertRaises(ValidationError):
            self.accrue(rule=rule)

    def test_employee_type_mismatch_is_rejected(self):
        rule = self.create_rule(
            employee_type="CONTRACT",
        )

        with self.assertRaises(ValidationError):
            self.accrue(rule=rule)

    def test_probation_condition_is_checked(self):
        rule = self.create_rule(
            probation_condition=(
                LeavePolicyRule.ProbationCondition.IN_PROBATION
            ),
        )

        with self.assertRaises(ValidationError):
            self.accrue(rule=rule)

    def test_month_end_rule_rejects_non_month_end_date(self):
        with self.assertRaises(ValidationError):
            self.accrue(
                accrual_date=date(2027, 3, 30),
            )

    def test_month_start_rule_rejects_non_month_start_date(self):
        rule = self.create_rule(
            accrual_timing=(
                LeavePolicyRule.AccrualTiming.MONTH_START
            ),
        )

        with self.assertRaises(ValidationError):
            self.accrue(rule=rule)

    def test_inactive_rule_is_rejected(self):
        rule = self.create_rule(rule_active=False)

        with self.assertRaises(ValidationError):
            self.accrue(rule=rule)

    def test_inactive_policy_is_rejected(self):
        rule = self.create_rule(policy_active=False)

        with self.assertRaises(ValidationError):
            self.accrue(rule=rule)

    def test_zero_monthly_accrual_creates_no_transaction(self):
        rule = self.create_rule(monthly_days="0.00")

        result = self.accrue(rule=rule)

        self.assertIsNone(result)
        self.assertEqual(
            LeaveBalanceTransaction.objects.count(),
            0,
        )
        self.assertEqual(
            LeaveBalance.objects.count(),
            0,
        )