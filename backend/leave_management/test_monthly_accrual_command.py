from datetime import date
from io import StringIO
from types import SimpleNamespace
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase

from leave_management.management.commands.process_monthly_accruals import (
    Command,
)


class FakeEmployeeQuerySet:
    def __init__(self, employees):
        self.employees = employees

    def select_related(self, *args):
        return self

    def order_by(self, *args):
        return self

    def count(self):
        return len(self.employees)

    def iterator(self):
        return iter(self.employees)


class MonthlyAccrualCommandTests(SimpleTestCase):
    def setUp(self):
        self.employee = SimpleNamespace(
            pk=4,
            organization_id=1,
            department_id=1,
            designation_id=1,
            employee_type="Full Time",
            probation_end_date=None,
        )

        self.rule = SimpleNamespace(
            pk=1,
            leave_type_id=1,
            monthly_accrual_days="1.50",
            accrual_timing="MONTH_END",
        )

        self.queryset = FakeEmployeeQuerySet([self.employee])

    @patch(
        "leave_management.management.commands.process_monthly_accruals."
        "Employee.objects.filter"
    )
    @patch(
        "leave_management.management.commands.process_monthly_accruals."
        "select_applicable_leave_rules"
    )
    @patch(
        "leave_management.management.commands.process_monthly_accruals."
        "accrue_monthly_leave"
    )
    def test_dry_run_does_not_call_accrual_service(
        self,
        mock_accrue,
        mock_select_rules,
        mock_employee_filter,
    ):
        mock_employee_filter.return_value = self.queryset
        mock_select_rules.return_value = {self.rule.pk: self.rule}

        output = StringIO()

        call_command(
            "process_monthly_accruals",
            accrual_date="2026-11-30",
            period_start="2026-01-01",
            period_end="2026-12-31",
            dry_run=True,
            stdout=output,
        )

        mock_accrue.assert_not_called()
        self.assertIn("WOULD PROCESS", output.getvalue())
        self.assertIn("DRY RUN completed", output.getvalue())

    @patch(
        "leave_management.management.commands.process_monthly_accruals."
        "Employee.objects.filter"
    )
    @patch(
        "leave_management.management.commands.process_monthly_accruals."
        "select_applicable_leave_rules"
    )
    @patch(
        "leave_management.management.commands.process_monthly_accruals."
        "accrue_monthly_leave"
    )
    def test_live_run_calls_accrual_service_for_due_rule(
        self,
        mock_accrue,
        mock_select_rules,
        mock_employee_filter,
    ):
        mock_employee_filter.return_value = self.queryset
        mock_select_rules.return_value = {self.rule.pk: self.rule}
        mock_accrue.return_value = SimpleNamespace(pk=101)

        call_command(
            "process_monthly_accruals",
            accrual_date="2026-11-30",
            period_start="2026-01-01",
            period_end="2026-12-31",
            stdout=StringIO(),
        )

        mock_accrue.assert_called_once_with(
            employee=self.employee,
            rule=self.rule,
            accrual_date=date(2026, 11, 30),
            period_start=date(2026, 1, 1),
            period_end=date(2026, 12, 31),
        )

    @patch(
        "leave_management.management.commands.process_monthly_accruals."
        "Employee.objects.filter"
    )
    @patch(
        "leave_management.management.commands.process_monthly_accruals."
        "select_applicable_leave_rules"
    )
    @patch(
        "leave_management.management.commands.process_monthly_accruals."
        "accrue_monthly_leave"
    )
    def test_rule_is_skipped_when_not_due(
        self,
        mock_accrue,
        mock_select_rules,
        mock_employee_filter,
    ):
        mock_employee_filter.return_value = self.queryset
        mock_select_rules.return_value = {self.rule.pk: self.rule}

        call_command(
            "process_monthly_accruals",
            accrual_date="2026-11-29",
            period_start="2026-01-01",
            period_end="2026-12-31",
            stdout=StringIO(),
        )

        mock_accrue.assert_not_called()

    def test_month_start_rule_is_due_on_first_day(self):
        rule = SimpleNamespace(accrual_timing="MONTH_START")

        self.assertTrue(
            Command._is_due(rule, date(2026, 11, 1))
        )
        self.assertFalse(
            Command._is_due(rule, date(2026, 11, 2))
        )

    def test_month_end_rule_is_due_on_last_day(self):
        self.assertTrue(
            Command._is_due(self.rule, date(2026, 11, 30))
        )
        self.assertFalse(
            Command._is_due(self.rule, date(2026, 11, 29))
        )

    def test_rejects_period_that_does_not_contain_accrual_date(self):
        with self.assertRaises(CommandError):
            call_command(
                "process_monthly_accruals",
                accrual_date="2026-11-30",
                period_start="2026-01-01",
                period_end="2026-10-31",
                stdout=StringIO(),
            )

    def test_rejects_period_start_after_period_end(self):
        with self.assertRaises(CommandError):
            call_command(
                "process_monthly_accruals",
                accrual_date="2026-11-30",
                period_start="2026-12-01",
                period_end="2026-01-01",
                stdout=StringIO(),
            )