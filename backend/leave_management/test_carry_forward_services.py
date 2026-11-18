from datetime import date
from unittest.mock import patch
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from employees.eligibility_services import (
    create_initial_employee_eligibility,
)

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
    LeaveCarryForwardConsumption,
    LeaveCarryForwardConsumptionReversal,
    LeaveCarryForwardLot,
    LeavePolicy,
    LeavePolicyRule,
    LeavePolicyVersion,
    LeaveRequest,
    LeaveType,
)
from leave_management.carry_forward_services import (
    reconcile_carry_forward_consumption,
    expire_carry_forward_lot,
)


class CarryForwardServiceTests(TestCase):
    def setUp(self):
        self.organization = Organization.objects.create(
            name="Carry Forward Test Organization",
            code="CARRYTEST",
        )

        self.department = Department.objects.create(
            name="Carry Forward Department",
            code="CFDEPT",
        )

        self.designation = Designation.objects.create(
            name="Carry Forward Designation",
            code="CFDES",
        )

        self.branch = Branch.objects.create(
            name="Carry Forward Branch",
            code="CFBRANCH",
            state="Karnataka",
            city="Mysuru",
        )

        User = get_user_model()

        publisher_user = User.objects.create_user(
            username="carry_forward_publisher",
            password="TestOnlyPassword123!",
        )

        self.publisher = UserProfile.objects.create(
            user=publisher_user,
            organization=self.organization,
            role=UserProfile.Role.SUPER_ADMIN,
        )

        self.leave_type = LeaveType.objects.create(
            organization=self.organization,
            code="CF_CASUAL",
            name="Carry Forward Casual Leave",
        )

        self.employee = Employee.objects.create(
            organization=self.organization,
            first_name="Carry",
            last_name="Forward",
            official_email="carry.forward@example.com",
            registered_mobile="9876543210",
            joining_date=date(2025, 1, 1),
            probation_end_date=date(2025, 6, 30),
            employee_type="FULL_TIME",
            department=self.department,
            designation=self.designation,
            branch=self.branch,
            status=Employee.Status.ACTIVE,
        )

        create_initial_employee_eligibility(
            employee=self.employee,
            effective_from=self.employee.joining_date,
        )

        self.balance = LeaveBalance.objects.create(
            organization=self.organization,
            employee=self.employee,
            leave_type=self.leave_type,
            period_start=date(2026, 1, 1),
            period_end=date(2026, 12, 31),
            entitled_days=Decimal("10.00"),
        )

        self.policy = LeavePolicy.objects.create(
            organization=self.organization,
            code="CF_POLICY",
            name="Carry Forward Test Policy",
        )

        self.version = LeavePolicyVersion.objects.create(
            policy=self.policy,
            version_number=1,
            effective_from=date(2026, 1, 1),
        )

        self.rule = LeavePolicyRule.objects.create(
            version=self.version,
            leave_type=self.leave_type,
            employee_type="FULL_TIME",
            probation_condition=(
                LeavePolicyRule.ProbationCondition.ANY
            ),
            monthly_accrual_days=Decimal("1.00"),
            accrual_timing=(
                LeavePolicyRule.AccrualTiming.MONTH_END
            ),
            allow_carry_forward=True,
            carry_forward_limit_days=Decimal("5.00"),
            carry_forward_interval_months=3,
            carry_forward_expiry_months=3,
        )

        self.version.status = LeavePolicyVersion.Status.PUBLISHED
        self.version.published_by = self.publisher
        self.version.published_at = timezone.now()
        self.version.save()

    def create_lot(
        self,
        *,
        granted_days="2.00",
        remaining_days=None,
        expires_on=date(2027, 1, 1),
        carried_forward_on=date(2026, 10, 1),
        key_suffix="1",
    ):
        if remaining_days is None:
            remaining_days = granted_days

        return LeaveCarryForwardLot.objects.create(
            balance=self.balance,
            policy_version=self.version,
            policy_rule=self.rule,
            source_period_start=date(2026, 7, 1),
            source_period_end=date(2026, 9, 30),
            carried_forward_on=carried_forward_on,
            expires_on=expires_on,
            granted_days=Decimal(granted_days),
            remaining_days=Decimal(remaining_days),
            idempotency_key=f"cf-test-lot-{key_suffix}",
        )

    def create_request(
        self,
        *,
        start_date=date(2026, 11, 2),
        end_date=date(2026, 11, 3),
        status=LeaveRequest.Status.APPROVED,
    ):
        return LeaveRequest.objects.create(
            organization=self.organization,
            employee=self.employee,
            leave_type=self.leave_type,
            manager_at_request=self.employee,
            start_date=start_date,
            end_date=end_date,
            working_days_count=2,
            reason="Carry-forward service test",
            status=status,
        )

    def reconcile(self):
        return reconcile_carry_forward_consumption(
            employee=self.employee,
            leave_type_id=self.leave_type.pk,
        )

    def create_consumption(
        self,
        *,
        lot,
        leave_request,
        consumed_on=date(2026, 11, 2),
        allocated_days="1.00",
        key="manual-test-consumption",
    ):
        consumption = LeaveCarryForwardConsumption.objects.create(
            lot=lot,
            leave_request=leave_request,
            consumed_on=consumed_on,
            allocated_days=Decimal(allocated_days),
            idempotency_key=key,
        )

        lot.remaining_days -= Decimal(allocated_days)
        lot.save(update_fields=["remaining_days", "updated_at"])

        return consumption

    def test_fifo_allocates_earliest_expiring_lot_first(self):
        earliest_lot = self.create_lot(
            granted_days="1.00",
            expires_on=date(2026, 12, 1),
            key_suffix="fifo-1",
        )

        later_lot = self.create_lot(
            granted_days="2.00",
            expires_on=date(2027, 1, 1),
            key_suffix="fifo-2",
        )

        leave_request = self.create_request()

        result = self.reconcile()

        consumptions = list(
            LeaveCarryForwardConsumption.objects.filter(
                leave_request=leave_request,
            ).order_by("consumed_on")
        )

        self.assertEqual(result["allocations_created"], 2)
        self.assertEqual(len(consumptions), 2)

        self.assertEqual(
            consumptions[0].consumed_on,
            date(2026, 11, 2),
        )
        self.assertEqual(
            consumptions[0].lot_id,
            earliest_lot.pk,
        )

        self.assertEqual(
            consumptions[1].consumed_on,
            date(2026, 11, 3),
        )
        self.assertEqual(
            consumptions[1].lot_id,
            later_lot.pk,
        )

        earliest_lot.refresh_from_db()
        later_lot.refresh_from_db()

        self.assertEqual(
            earliest_lot.remaining_days,
            Decimal("0.00"),
        )
        self.assertEqual(
            later_lot.remaining_days,
            Decimal("1.00"),
        )

    def test_repeated_reconciliation_does_not_duplicate_allocations(self):
        lot = self.create_lot(key_suffix="idempotent")
        leave_request = self.create_request()

        first_result = self.reconcile()
        second_result = self.reconcile()

        self.assertEqual(first_result["allocations_created"], 2)
        self.assertEqual(second_result["allocations_created"], 0)
        self.assertEqual(second_result["reversals_created"], 0)

        self.assertEqual(
            LeaveCarryForwardConsumption.objects.filter(
                lot=lot,
                leave_request=leave_request,
            ).count(),
            2,
        )

        lot.refresh_from_db()

        self.assertEqual(
            lot.remaining_days,
            Decimal("0.00"),
        )

    def test_cancelled_request_creates_reversals_and_restores_lot(self):
        lot = self.create_lot(key_suffix="cancel")
        leave_request = self.create_request()

        self.reconcile()

        self.assertEqual(
            LeaveCarryForwardConsumption.objects.filter(
                leave_request=leave_request,
            ).count(),
            2,
        )

        leave_request.status = LeaveRequest.Status.CANCELLED
        leave_request.save(update_fields=["status", "updated_at"])

        result = self.reconcile()

        lot.refresh_from_db()

        self.assertEqual(result["reversals_created"], 2)
        self.assertEqual(
            result["restored_days"],
            Decimal("2.00"),
        )
        self.assertEqual(
            lot.remaining_days,
            Decimal("2.00"),
        )

        self.assertEqual(
            LeaveCarryForwardConsumptionReversal.objects.filter(
                consumption__leave_request=leave_request,
            ).count(),
            2,
        )

        # Original consumption history must remain.
        self.assertEqual(
            LeaveCarryForwardConsumption.objects.filter(
                leave_request=leave_request,
            ).count(),
            2,
        )

    def test_changed_request_dates_reverse_only_invalid_allocations(self):
        lot = self.create_lot(key_suffix="date-change")
        leave_request = self.create_request()

        self.reconcile()

        # The request now covers only November 3.
        leave_request.start_date = date(2026, 11, 3)
        leave_request.end_date = date(2026, 11, 3)
        leave_request.working_days_count = 1
        leave_request.save(
            update_fields=[
                "start_date",
                "end_date",
                "working_days_count",
                "updated_at",
            ]
        )

        result = self.reconcile()

        lot.refresh_from_db()

        self.assertEqual(result["reversals_created"], 1)
        self.assertEqual(
            result["restored_days"],
            Decimal("1.00"),
        )
        self.assertEqual(
            lot.remaining_days,
            Decimal("1.00"),
        )

        self.assertEqual(
            LeaveCarryForwardConsumptionReversal.objects.filter(
                consumption__leave_request=leave_request,
            ).count(),
            1,
        )

        # The still-valid November 3 allocation remains active.
        active_consumption = (
            LeaveCarryForwardConsumption.objects.filter(
                leave_request=leave_request,
                consumed_on=date(2026, 11, 3),
            ).first()
        )

        self.assertIsNotNone(active_consumption)

        self.assertFalse(
            LeaveCarryForwardConsumptionReversal.objects.filter(
                consumption=active_consumption,
            ).exists()
        )

    def test_expired_lot_does_not_restore_cancelled_consumption(self):
        lot = self.create_lot(
            granted_days="1.00",
            remaining_days="1.00",
            carried_forward_on=date(2026, 10, 1),
            expires_on=date(2026, 11, 5),
            key_suffix="expired-reversal",
        )

        leave_request = self.create_request(
            start_date=date(2026, 11, 2),
            end_date=date(2026, 11, 2),
        )
        leave_request.working_days_count = 1
        leave_request.save(update_fields=["working_days_count"])

        consumption = self.create_consumption(
            lot=lot,
            leave_request=leave_request,
            consumed_on=date(2026, 11, 2),
            key="expired-lot-consumption",
        )

        leave_request.status = LeaveRequest.Status.CANCELLED
        leave_request.save(update_fields=["status", "updated_at"])

        result = self.reconcile()

        lot.refresh_from_db()

        self.assertEqual(result["reversals_created"], 0)
        self.assertEqual(
            result["restored_days"],
            Decimal("0.00"),
        )
        self.assertEqual(
            lot.remaining_days,
            Decimal("0.00"),
        )

        self.assertTrue(
            LeaveCarryForwardConsumption.objects.filter(
                pk=consumption.pk,
            ).exists()
        )

        self.assertFalse(
            LeaveCarryForwardConsumptionReversal.objects.filter(
                consumption=consumption,
            ).exists()
        )

    def test_expiry_reduces_balance_by_remaining_days(self):
        lot = self.create_lot(
            granted_days="3.00",
            remaining_days="2.00",
            expires_on=date(2026, 11, 10),
            key_suffix="partial-expiry",
        )

        result = expire_carry_forward_lot(
            lot_id=lot.pk,
            expiry_date=date(2026, 11, 11),
        )

        lot.refresh_from_db()
        self.balance.refresh_from_db()

        self.assertEqual(result["status"], "expired")
        self.assertEqual(
            result["expired_days"],
            Decimal("2.00"),
        )
        self.assertEqual(
            lot.remaining_days,
            Decimal("0.00"),
        )
        self.assertEqual(
            self.balance.entitled_days,
            Decimal("8.00"),
        )

        transaction_record = (
            LeaveBalanceTransaction.objects.get(
                idempotency_key=f"carry-forward-expiry:{lot.pk}",
            )
        )

        self.assertEqual(
            transaction_record.transaction_type,
            LeaveBalanceTransaction.TransactionType.EXPIRY,
        )
        self.assertEqual(
            transaction_record.days,
            Decimal("-2.00"),
        )

    def test_full_expiry_removes_entire_remaining_amount(self):
        lot = self.create_lot(
            granted_days="3.00",
            remaining_days="3.00",
            expires_on=date(2026, 11, 10),
            key_suffix="full-expiry",
        )

        result = expire_carry_forward_lot(
            lot_id=lot.pk,
            expiry_date=date(2026, 11, 11),
        )

        lot.refresh_from_db()
        self.balance.refresh_from_db()

        self.assertEqual(result["status"], "expired")
        self.assertEqual(
            result["expired_days"],
            Decimal("3.00"),
        )
        self.assertEqual(
            lot.remaining_days,
            Decimal("0.00"),
        )
        self.assertEqual(
            self.balance.entitled_days,
            Decimal("7.00"),
        )

    def test_repeated_expiry_does_not_deduct_balance_twice(self):
        lot = self.create_lot(
            granted_days="2.00",
            remaining_days="2.00",
            expires_on=date(2026, 11, 10),
            key_suffix="repeat-expiry",
        )

        first_result = expire_carry_forward_lot(
            lot_id=lot.pk,
            expiry_date=date(2026, 11, 11),
        )

        second_result = expire_carry_forward_lot(
            lot_id=lot.pk,
            expiry_date=date(2026, 11, 12),
        )

        self.balance.refresh_from_db()

        self.assertEqual(first_result["status"], "expired")
        self.assertEqual(second_result["status"], "already_expired")

        self.assertEqual(
            self.balance.entitled_days,
            Decimal("8.00"),
        )

        self.assertEqual(
            LeaveBalanceTransaction.objects.filter(
                idempotency_key=f"carry-forward-expiry:{lot.pk}",
                transaction_type=(
                    LeaveBalanceTransaction.TransactionType.EXPIRY
                ),
            ).count(),
            1,
        )

    def test_expiry_before_due_date_does_not_change_lot_or_balance(self):
        lot = self.create_lot(
            granted_days="2.00",
            remaining_days="2.00",
            expires_on=date(2026, 12, 1),
            key_suffix="not-due",
        )

        result = expire_carry_forward_lot(
            lot_id=lot.pk,
            expiry_date=date(2026, 11, 30),
        )

        lot.refresh_from_db()
        self.balance.refresh_from_db()

        self.assertEqual(result["status"], "not_due")
        self.assertEqual(
            lot.remaining_days,
            Decimal("2.00"),
        )
        self.assertEqual(
            self.balance.entitled_days,
            Decimal("10.00"),
        )

        self.assertFalse(
            LeaveBalanceTransaction.objects.filter(
                idempotency_key=f"carry-forward-expiry:{lot.pk}",
            ).exists()
        )

    def test_multiple_requests_are_processed_in_date_order(self):
        lot = self.create_lot(
            granted_days="4.00",
            key_suffix="multiple-requests",
        )

        first_request = self.create_request(
            start_date=date(2026, 11, 2),
            end_date=date(2026, 11, 3),
        )

        second_request = self.create_request(
            start_date=date(2026, 11, 4),
            end_date=date(2026, 11, 5),
        )

        result = self.reconcile()

        self.assertEqual(result["allocations_created"], 4)

        consumptions = list(
            LeaveCarryForwardConsumption.objects.filter(
                lot=lot,
            ).order_by("consumed_on")
        )

        self.assertEqual(len(consumptions), 4)

        self.assertEqual(
            [item.leave_request_id for item in consumptions],
            [
                first_request.pk,
                first_request.pk,
                second_request.pk,
                second_request.pk,
            ],
        )

        lot.refresh_from_db()

        self.assertEqual(
            lot.remaining_days,
            Decimal("0.00"),
        )

    def test_insufficient_carry_forward_days_never_make_lot_negative(self):
        lot = self.create_lot(
            granted_days="1.00",
            key_suffix="insufficient",
        )

        leave_request = self.create_request(
            start_date=date(2026, 11, 2),
            end_date=date(2026, 11, 4),
        )

        result = self.reconcile()

        lot.refresh_from_db()

        self.assertEqual(result["allocations_created"], 1)

        self.assertEqual(
            LeaveCarryForwardConsumption.objects.filter(
                lot=lot,
                leave_request=leave_request,
            ).count(),
            1,
        )

        self.assertEqual(
            lot.remaining_days,
            Decimal("0.00"),
        )

        self.assertGreaterEqual(
            lot.remaining_days,
            Decimal("0.00"),
        )

    def test_lot_balance_matches_active_consumption_history(self):
        lot = self.create_lot(
            granted_days="4.00",
            key_suffix="balance-invariant",
        )

        first_request = self.create_request(
            start_date=date(2026, 11, 2),
            end_date=date(2026, 11, 3),
        )

        second_request = self.create_request(
            start_date=date(2026, 11, 4),
            end_date=date(2026, 11, 5),
        )

        self.reconcile()

        active_consumption = (
            LeaveCarryForwardConsumption.objects.filter(
                lot=lot,
            ).exclude(
                pk__in=LeaveCarryForwardConsumptionReversal.objects.values_list(
                    "consumption_id",
                    flat=True,
                )
            )
        )

        active_days = sum(
            (
                item.allocated_days
                for item in active_consumption
            ),
            Decimal("0.00"),
        )

        lot.refresh_from_db()

        self.assertEqual(
            active_days + lot.remaining_days,
            lot.granted_days,
        )

        self.assertEqual(
            active_consumption.filter(
                leave_request=first_request,
            ).count(),
            2,
        )

        self.assertEqual(
            active_consumption.filter(
                leave_request=second_request,
            ).count(),
            2,
        )

    def test_expiry_failure_rolls_back_all_database_changes(self):
        lot = self.create_lot(
            granted_days="2.00",
            remaining_days="2.00",
            expires_on=date(2026, 11, 10),
            key_suffix="expiry-rollback",
        )

        original_balance = self.balance.entitled_days

        with patch.object(
            LeaveCarryForwardLot,
            "save",
            side_effect=RuntimeError(
                "Simulated failure while updating carry-forward lot."
            ),
        ):
            with self.assertRaises(RuntimeError):
                expire_carry_forward_lot(
                    lot_id=lot.pk,
                    expiry_date=date(2026, 11, 11),
                )

        lot.refresh_from_db()
        self.balance.refresh_from_db()

        self.assertEqual(
            lot.remaining_days,
            Decimal("2.00"),
        )

        self.assertEqual(
            self.balance.entitled_days,
            original_balance,
        )

        self.assertFalse(
            LeaveBalanceTransaction.objects.filter(
                idempotency_key=f"carry-forward-expiry:{lot.pk}",
            ).exists()
        )

    def test_reconciliation_does_not_affect_another_organization(self):
        other_organization = Organization.objects.create(
            name="Other Carry Forward Organization",
            code="OTHERCF",
        )

        other_user = get_user_model().objects.create_user(
            username="other_cf_publisher",
            password="TestOnlyPassword123!",
        )

        other_publisher = UserProfile.objects.create(
            user=other_user,
            organization=other_organization,
            role=UserProfile.Role.SUPER_ADMIN,
        )

        other_leave_type = LeaveType.objects.create(
            organization=other_organization,
            code="OTHER_CF_CASUAL",
            name="Other Organization Casual Leave",
        )

        other_employee = Employee.objects.create(
            organization=other_organization,
            first_name="Other",
            last_name="Employee",
            official_email="other.employee@example.com",
            registered_mobile="9876543211",
            joining_date=date(2025, 1, 1),
            probation_end_date=date(2025, 6, 30),
            employee_type="FULL_TIME",
            department=self.department,
            designation=self.designation,
            branch=self.branch,
            status=Employee.Status.ACTIVE,
        )

        create_initial_employee_eligibility(
            employee=other_employee,
            effective_from=other_employee.joining_date,
        )

        other_balance = LeaveBalance.objects.create(
            organization=other_organization,
            employee=other_employee,
            leave_type=other_leave_type,
            period_start=date(2026, 1, 1),
            period_end=date(2026, 12, 31),
            entitled_days=Decimal("10.00"),
        )

        other_policy = LeavePolicy.objects.create(
            organization=other_organization,
            code="OTHER_CF_POLICY",
            name="Other Organization Carry Forward Policy",
        )

        other_version = LeavePolicyVersion.objects.create(
            policy=other_policy,
            version_number=1,
            effective_from=date(2026, 1, 1),
        )

        other_rule = LeavePolicyRule.objects.create(
            version=other_version,
            leave_type=other_leave_type,
            employee_type="FULL_TIME",
            probation_condition=(
                LeavePolicyRule.ProbationCondition.ANY
            ),
            monthly_accrual_days=Decimal("1.00"),
            accrual_timing=(
                LeavePolicyRule.AccrualTiming.MONTH_END
            ),
            allow_carry_forward=True,
            carry_forward_limit_days=Decimal("5.00"),
            carry_forward_interval_months=3,
            carry_forward_expiry_months=3,
        )

        other_version.status = LeavePolicyVersion.Status.PUBLISHED
        other_version.published_by = other_publisher
        other_version.published_at = timezone.now()
        other_version.save()

        other_lot = LeaveCarryForwardLot.objects.create(
            balance=other_balance,
            policy_version=other_version,
            policy_rule=other_rule,
            source_period_start=date(2026, 7, 1),
            source_period_end=date(2026, 9, 30),
            carried_forward_on=date(2026, 10, 1),
            expires_on=date(2027, 1, 1),
            granted_days=Decimal("2.00"),
            remaining_days=Decimal("2.00"),
            idempotency_key="other-org-cf-lot",
        )

        other_request = LeaveRequest.objects.create(
            organization=other_organization,
            employee=other_employee,
            leave_type=other_leave_type,
            manager_at_request=other_employee,
            start_date=date(2026, 11, 2),
            end_date=date(2026, 11, 3),
            working_days_count=2,
            reason="Other organization isolation test",
            status=LeaveRequest.Status.APPROVED,
        )

        # Create a carry-forward lot for the first organization.
        own_lot = self.create_lot(
            granted_days="2.00",
            remaining_days="2.00",
            expires_on=date(2027, 1, 1),
            carried_forward_on=date(2026, 10, 1),
            key_suffix="own",
        )

        # Create an approved request in the first organization too.
        own_request = self.create_request(
            start_date=date(2026, 11, 2),
            end_date=date(2026, 11, 3),
        )

        # Reconcile only the first organization's employee.
        # Use the test dates explicitly so the result is deterministic.
        with patch("leave_management.carry_forward_services.timezone.localdate") as mocked_date:
            mocked_date.return_value = date(2026, 11, 11)
            result = self.reconcile()

        self.assertEqual(result["allocations_created"], 2)

        # The first organization's request is reconciled.
        self.assertEqual(
            LeaveCarryForwardConsumption.objects.filter(
                leave_request=own_request,
            ).count(),
            2,
        )

        # The other organization's request must remain untouched.
        self.assertEqual(
            LeaveCarryForwardConsumption.objects.filter(
                leave_request=other_request,
            ).count(),
            0,
        )

        other_lot.refresh_from_db()
        other_balance.refresh_from_db()

        self.assertEqual(
            other_lot.remaining_days,
            Decimal("2.00"),
        )

        self.assertEqual(
            other_balance.entitled_days,
            Decimal("10.00"),
        )

        self.assertFalse(
            LeaveBalanceTransaction.objects.filter(
                organization=other_organization,
                transaction_type=(
                    LeaveBalanceTransaction.TransactionType.EXPIRY
                ),
            ).exists()
        )
