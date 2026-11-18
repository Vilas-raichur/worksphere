from datetime import date
from decimal import Decimal
from unittest.mock import patch

from django.core.exceptions import ValidationError

from employees.eligibility_services import (
    create_initial_employee_eligibility,
    get_employee_eligibility_for_date,
    record_employee_eligibility_change,
)

from employees.models import Employee

from leave_management.models import (
    LeaveBalanceTransaction,
    LeaveCarryForwardLot,
)

from leave_management.carry_forward_generation_services import (
    _calculate_unused_accruals_by_rule,
    _get_candidate_carry_forward_rules,
    _get_expected_accruals,
    generate_carry_forward_lots,
)
from leave_management.test_carry_forward_services import (
    CarryForwardServiceTests,
)


class CarryForwardGenerationTests(CarryForwardServiceTests):

    def create_accrual(self, effective_date, days="1.00"):
        return LeaveBalanceTransaction.objects.create(
            organization=self.organization,
            employee=self.employee,
            leave_type=self.leave_type,
            balance=self.balance,
            transaction_type=(
                LeaveBalanceTransaction.TransactionType.ACCRUAL
            ),
            days=Decimal(days),
            effective_date=effective_date,
            policy_version=self.version,
            policy_rule=self.rule,
            idempotency_key=(
                f"generation-test-{effective_date.isoformat()}"
            ),
            description="Carry-forward generation test accrual",
        )

    def create_quarter_accruals(self, days="1.00"):
        self.create_accrual(date(2026, 1, 31), days)
        self.create_accrual(date(2026, 2, 28), days)
        self.create_accrual(date(2026, 3, 31), days)

    def generate_for_first_quarter(self, dry_run=False):
        return generate_carry_forward_lots(
            employee=self.employee,
            processing_date=date(2026, 4, 1),
            dry_run=dry_run,
        )

    def test_candidate_rule_is_found_without_accrual_transactions(self):
        rules = _get_candidate_carry_forward_rules(
            employee=self.employee,
            balance=self.balance,
        )

        self.assertIn(self.rule, rules)

        self.assertFalse(
            LeaveBalanceTransaction.objects.filter(
                employee=self.employee,
                balance=self.balance,
                transaction_type=(
                    LeaveBalanceTransaction.TransactionType.ACCRUAL
                ),
            ).exists()
        )

    def test_expected_accruals_ignore_dates_before_joining(self):
        employee = Employee.objects.create(
            organization=self.organization,
            first_name="New",
            last_name="Joiner",
            official_email="new.joiner@example.com",
            registered_mobile="9876543211",
            joining_date=date(2026, 2, 15),
            probation_end_date=None,
            employee_type="FULL_TIME",
            department=self.department,
            designation=self.designation,
            branch=self.branch,
            status=Employee.Status.ACTIVE,
        )

        create_initial_employee_eligibility(
            employee=employee,
            effective_from=employee.joining_date,
        )

        expected = _get_expected_accruals(
            employee=employee,
            leave_type_id=self.leave_type.pk,
            interval_start=date(2026, 1, 1),
            interval_end=date(2026, 3, 31),
        )

        expected_dates = [
            accrual_date
            for accrual_date, rule in expected
        ]

        self.assertEqual(
            expected_dates,
            [
                date(2026, 2, 28),
                date(2026, 3, 31),
            ],
        )

    @patch(
        "leave_management.carry_forward_generation_services."
        "reconcile_carry_forward_consumption"
    )
    @patch(
        "leave_management.carry_forward_generation_services."
        "get_attendance_policy"
    )
    def test_generation_creates_correct_lot(
        self,
        mock_attendance_policy,
        mock_reconcile,
    ):
        mock_attendance_policy.return_value = None

        self.create_quarter_accruals()

        result = self.generate_for_first_quarter()

        self.assertEqual(result["created"], 1)
        self.assertEqual(result["skipped"], 0)
        self.assertEqual(result["failed"], 0)

        lot = LeaveCarryForwardLot.objects.get(
            balance=self.balance,
            policy_rule=self.rule,
        )

        self.assertEqual(
            lot.source_period_start,
            date(2026, 1, 1),
        )
        self.assertEqual(
            lot.source_period_end,
            date(2026, 3, 31),
        )
        self.assertEqual(
            lot.carried_forward_on,
            date(2026, 4, 1),
        )
        self.assertEqual(
            lot.expires_on,
            date(2026, 7, 1),
        )
        self.assertEqual(
            lot.granted_days,
            Decimal("3.00"),
        )
        self.assertEqual(
            lot.remaining_days,
            Decimal("3.00"),
        )

        self.balance.refresh_from_db()

        self.assertEqual(
            self.balance.entitled_days,
            Decimal("10.00"),
        )

    @patch(
        "leave_management.carry_forward_generation_services."
        "reconcile_carry_forward_consumption"
    )
    @patch(
        "leave_management.carry_forward_generation_services."
        "get_attendance_policy"
    )
    def test_generation_respects_carry_forward_cap(
        self,
        mock_attendance_policy,
        mock_reconcile,
    ):
        mock_attendance_policy.return_value = None

        self.create_quarter_accruals(days="3.00")

        result = self.generate_for_first_quarter()

        self.assertEqual(result["created"], 1)

        lot = LeaveCarryForwardLot.objects.get(
            balance=self.balance,
            policy_rule=self.rule,
        )

        self.assertEqual(
            lot.granted_days,
            Decimal("5.00"),
        )

    @patch(
        "leave_management.carry_forward_generation_services."
        "reconcile_carry_forward_consumption"
    )
    @patch(
        "leave_management.carry_forward_generation_services."
        "get_attendance_policy"
    )
    def test_repeated_generation_does_not_create_duplicate_lot(
        self,
        mock_attendance_policy,
        mock_reconcile,
    ):
        mock_attendance_policy.return_value = None

        self.create_quarter_accruals()

        first_result = self.generate_for_first_quarter()
        second_result = self.generate_for_first_quarter()

        self.assertEqual(first_result["created"], 1)
        self.assertEqual(second_result["created"], 0)
        self.assertEqual(second_result["skipped"], 1)

        self.assertEqual(
            LeaveCarryForwardLot.objects.filter(
                balance=self.balance,
                policy_rule=self.rule,
            ).count(),
            1,
        )

    @patch(
        "leave_management.carry_forward_generation_services."
        "reconcile_carry_forward_consumption"
    )
    def test_missing_expected_accrual_stops_generation(
        self,
        mock_reconcile,
    ):
        self.create_accrual(date(2026, 1, 31))
        self.create_accrual(date(2026, 3, 31))

        with self.assertRaises(ValidationError):
            self.generate_for_first_quarter()

        mock_reconcile.assert_not_called()

        self.assertFalse(
            LeaveCarryForwardLot.objects.filter(
                balance=self.balance,
            ).exists()
        )

    def test_ordinary_leave_usage_consumes_oldest_accrual_first(self):
        self.create_quarter_accruals()

        with patch(
            "leave_management.carry_forward_generation_services."
            "_get_approved_ordinary_usage_dates",
            return_value=[date(2026, 2, 15)],
        ):
            unused = _calculate_unused_accruals_by_rule(
                employee=self.employee,
                balance=self.balance,
                interval_start=date(2026, 1, 1),
                interval_end=date(2026, 3, 31),
                carry_forward_dates=set(),
            )

        self.assertEqual(
            unused[self.rule.pk],
            Decimal("2.00"),
        )

    def test_existing_lot_is_removed_from_ordinary_accruals(self):
        self.create_quarter_accruals()

        lot = LeaveCarryForwardLot(
            balance=self.balance,
            policy_version=self.version,
            policy_rule=self.rule,
            source_period_start=date(2026, 1, 1),
            source_period_end=date(2026, 3, 31),
            carried_forward_on=date(2026, 4, 1),
            expires_on=date(2026, 7, 1),
            granted_days=Decimal("1.00"),
            remaining_days=Decimal("1.00"),
            idempotency_key="generation-existing-lot-test",
        )
        lot.full_clean()
        lot.save()

        unused = _calculate_unused_accruals_by_rule(
            employee=self.employee,
            balance=self.balance,
            interval_start=date(2026, 1, 1),
            interval_end=date(2026, 3, 31),
            carry_forward_dates=set(),
        )

        self.assertEqual(
            unused[self.rule.pk],
            Decimal("2.00"),
        )



    def test_eligibility_history_uses_effective_date_boundary(self):
        old_probation_end_date = self.employee.probation_end_date
        new_probation_end_date = date(2026, 6, 30)

        self.employee.probation_end_date = new_probation_end_date
        self.employee.save(
            update_fields=[
                "probation_end_date",
                "updated_at",
            ]
        )

        record_employee_eligibility_change(
            employee=self.employee,
            effective_from=date(2026, 2, 1),

        )

        previous_eligibility = get_employee_eligibility_for_date(
            employee=self.employee,
            eligibility_date=date(2026, 1, 31),
        )

        updated_eligibility = get_employee_eligibility_for_date(
            employee=self.employee,
            eligibility_date=date(2026, 2, 1),
        )

        self.assertEqual(
            previous_eligibility.probation_end_date,
            old_probation_end_date,
        )

        self.assertEqual(
            updated_eligibility.probation_end_date,
            new_probation_end_date,
        )

        self.assertEqual(
            previous_eligibility.effective_until,
            date(2026, 1, 31),
        )

        self.assertEqual(
            updated_eligibility.effective_from,
            date(2026, 2, 1),
        )

    def test_expected_accruals_fail_when_history_is_missing(self):
        employee_without_history = Employee.objects.create(
            organization=self.organization,
            first_name="Missing",
            last_name="History",
            official_email="missing.history@example.com",
            registered_mobile="9876543212",
            joining_date=date(2025, 1, 1),
            probation_end_date=None,
            employee_type="FULL_TIME",
            department=self.department,
            designation=self.designation,
            branch=self.branch,
            status=Employee.Status.ACTIVE,
        )

        with self.assertRaises(ValidationError):
            _get_expected_accruals(
                employee=employee_without_history,
                leave_type_id=self.leave_type.pk,
                interval_start=date(2026, 1, 1),
                interval_end=date(2026, 1, 31),
            )

    @patch(
        "leave_management.carry_forward_generation_services."
        "get_attendance_policy"
    )

    def test_dry_run_rolls_back_reconciliation_writes(
        self,
        mock_attendance_policy,
    ):
        mock_attendance_policy.return_value = None

        self.create_quarter_accruals()

        original_first_name = self.employee.first_name

        def reconciliation_with_database_write(**kwargs):
            from employees.models import Employee

            Employee.objects.filter(
                pk=self.employee.pk,
            ).update(
                first_name="Dry Run Changed",
            )

        with patch(
            "leave_management.carry_forward_generation_services."
            "reconcile_carry_forward_consumption",
            side_effect=reconciliation_with_database_write,
        ):
            result = self.generate_for_first_quarter(
                dry_run=True,
            )

        self.employee.refresh_from_db()

        self.assertEqual(
            self.employee.first_name,
            original_first_name,
        )

        self.assertEqual(result["created"], 0)

        self.assertEqual(
            sum(
                1
                for item in result["results"]
                if item["status"] == "dry_run"
            ),
            1,
        )

        self.assertFalse(
            LeaveCarryForwardLot.objects.filter(
                balance=self.balance,
            ).exists()
        )