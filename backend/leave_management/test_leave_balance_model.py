from datetime import date

from django.core.exceptions import ValidationError
from django.test import TestCase

from accounts.models import Organization
from employees.models import Branch, Department, Designation, Employee
from leave_management.models import LeaveBalance, LeaveType


class LeaveBalanceModelTests(TestCase):
    def setUp(self):
        self.organization = Organization.objects.create(
            name="Leave Balance Test Organization",
            code="LBTORG",
        )

        self.department = Department.objects.create(
            name="Leave Balance Test Department",
            code="LBTDEP",
        )

        self.designation = Designation.objects.create(
            name="Leave Balance Test Designation",
            code="LBTDES",
        )

        self.branch = Branch.objects.create(
            name="Leave Balance Test Branch",
            code="LBTBR",
            state="Karnataka",
            city="Bengaluru",
        )

        self.employee = self.create_employee(
            self.organization,
            "001",
        )

        self.leave_type = LeaveType.objects.create(
            organization=self.organization,
            code="ANNUAL",
            name="Annual Leave",
        )

    def create_employee(self, organization, suffix):
        return Employee.objects.create(
            employee_id=f"LB-TEST-{suffix}",
            onboarding_reference=f"ONB-LB-{suffix}",
            organization=organization,
            first_name="Test",
            last_name=f"Employee {suffix}",
            official_email=(
                f"leave.balance.{suffix}@example.com"
            ),
            registered_mobile="9876543210",
            joining_date=date(2026, 1, 1),
            employee_type="FULL_TIME",
            department=self.department,
            designation=self.designation,
            branch=self.branch,
            status=Employee.Status.ACTIVE,
        )

    def create_balance(
        self,
        period_start=date(2026, 1, 1),
        period_end=date(2026, 12, 31),
        entitled_days=12,
        employee=None,
        leave_type=None,
        organization=None,
    ):
        return LeaveBalance(
            organization=organization or self.organization,
            employee=employee or self.employee,
            leave_type=leave_type or self.leave_type,
            period_start=period_start,
            period_end=period_end,
            entitled_days=entitled_days,
        )

    def test_valid_balance_can_be_saved(self):
        balance = self.create_balance()

        balance.full_clean()
        balance.save()

        self.assertEqual(LeaveBalance.objects.count(), 1)
        self.assertEqual(balance.entitled_days, 12)

    def test_end_date_before_start_date_is_rejected(self):
        balance = self.create_balance(
            period_start=date(2026, 12, 31),
            period_end=date(2026, 1, 1),
        )

        with self.assertRaises(ValidationError):
            balance.full_clean()

    def test_employee_from_another_organization_is_rejected(self):
        other_organization = Organization.objects.create(
            name="Other Leave Balance Organization",
            code="LBTORG2",
        )

        other_employee = self.create_employee(
            other_organization,
            "002",
        )

        balance = self.create_balance(
            employee=other_employee,
        )

        with self.assertRaises(ValidationError) as context:
            balance.full_clean()

        self.assertIn(
            "employee",
            context.exception.message_dict,
        )

    def test_leave_type_from_another_organization_is_rejected(self):
        other_organization = Organization.objects.create(
            name="Third Leave Balance Organization",
            code="LBTORG3",
        )

        other_leave_type = LeaveType.objects.create(
            organization=other_organization,
            code="ANNUAL",
            name="Annual Leave",
        )

        balance = self.create_balance(
            leave_type=other_leave_type,
        )

        with self.assertRaises(ValidationError) as context:
            balance.full_clean()

        self.assertIn(
            "leave_type",
            context.exception.message_dict,
        )

    def test_overlapping_period_is_rejected(self):
        first_balance = self.create_balance(
            period_start=date(2026, 1, 1),
            period_end=date(2026, 6, 30),
        )
        first_balance.full_clean()
        first_balance.save()

        overlapping_balance = self.create_balance(
            period_start=date(2026, 6, 1),
            period_end=date(2026, 12, 31),
        )

        with self.assertRaises(ValidationError) as context:
            overlapping_balance.full_clean()

        self.assertIn(
            "period_start",
            context.exception.message_dict,
        )

    def test_non_overlapping_periods_are_allowed(self):
        first_balance = self.create_balance(
            period_start=date(2026, 1, 1),
            period_end=date(2026, 6, 30),
        )
        first_balance.full_clean()
        first_balance.save()

        second_balance = self.create_balance(
            period_start=date(2026, 7, 1),
            period_end=date(2026, 12, 31),
        )

        second_balance.full_clean()
        second_balance.save()

        self.assertEqual(LeaveBalance.objects.count(), 2)

    def test_negative_entitlement_is_rejected(self):
        balance = self.create_balance(entitled_days=-1)

        with self.assertRaises(ValidationError) as context:
            balance.full_clean()

        self.assertIn(
            "entitled_days",
            context.exception.message_dict,
        )