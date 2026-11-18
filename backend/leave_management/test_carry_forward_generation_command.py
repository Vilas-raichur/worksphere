from io import StringIO
from types import SimpleNamespace
from unittest.mock import patch

from django.core.management.base import CommandError
from django.test import SimpleTestCase

from employees.models import Employee
from leave_management.management.commands.process_carry_forward_generations import (
    Command,
)


class CarryForwardGenerationCommandTests(SimpleTestCase):

    def setUp(self):
        self.employee_1 = SimpleNamespace(pk=101)
        self.employee_2 = SimpleNamespace(pk=102)

        self.queryset = SimpleNamespace(
            count=lambda: 2,
            iterator=lambda: iter(
                [self.employee_1, self.employee_2]
            ),
        )

        self.stdout = StringIO()
        self.stderr = StringIO()

        self.command = Command(
            stdout=self.stdout,
            stderr=self.stderr,
        )

    @patch(
        "leave_management.management.commands."
        "process_carry_forward_generations.generate_carry_forward_lots"
    )
    @patch(
        "leave_management.management.commands."
        "process_carry_forward_generations.Employee.objects.filter"
    )
    def test_dry_run_processes_employees_without_creating_lots(
        self,
        mock_employee_filter,
        mock_generate,
    ):
        mock_employee_filter.return_value.order_by.return_value = (
            self.queryset
        )

        mock_generate.side_effect = [
            {
                "employee_id": 101,
                "created": 0,
                "skipped": 0,
                "failed": 0,
                "results": [
                    {"status": "dry_run"},
                    {"status": "dry_run"},
                ],
            },
            {
                "employee_id": 102,
                "created": 0,
                "skipped": 1,
                "failed": 0,
                "results": [],
            },
        ]

        self.command.handle(
            date="2026-11-11",
            dry_run=True,
        )

        self.assertEqual(mock_generate.call_count, 2)

        for call in mock_generate.call_args_list:
            self.assertTrue(call.kwargs["dry_run"])
            self.assertEqual(
                str(call.kwargs["processing_date"]),
                "2026-11-11",
            )

        output = self.stdout.getvalue()

        self.assertIn("Lots that would be created: 2", output)
        self.assertIn("Already generated / skipped: 1", output)
        self.assertIn("Failures: 0", output)

    @patch(
        "leave_management.management.commands."
        "process_carry_forward_generations.generate_carry_forward_lots"
    )
    @patch(
        "leave_management.management.commands."
        "process_carry_forward_generations.Employee.objects.filter"
    )
    def test_normal_run_aggregates_created_and_skipped_lots(
        self,
        mock_employee_filter,
        mock_generate,
    ):
        mock_employee_filter.return_value.order_by.return_value = (
            self.queryset
        )

        mock_generate.side_effect = [
            {
                "employee_id": 101,
                "created": 2,
                "skipped": 0,
                "failed": 0,
                "results": [],
            },
            {
                "employee_id": 102,
                "created": 1,
                "skipped": 1,
                "failed": 0,
                "results": [],
            },
        ]

        self.command.handle(
            date="2026-11-11",
            dry_run=False,
        )

        for call in mock_generate.call_args_list:
            self.assertFalse(call.kwargs["dry_run"])

        output = self.stdout.getvalue()

        self.assertIn("Lots created: 3", output)
        self.assertIn("Already generated / skipped: 1", output)
        self.assertIn("Failures: 0", output)

    @patch(
        "leave_management.management.commands."
        "process_carry_forward_generations.Employee.objects.filter"
    )
    def test_invalid_date_is_rejected_before_employee_query(
        self,
        mock_employee_filter,
    ):
        with self.assertRaises(CommandError):
            self.command.handle(
                date="11-11-2026",
                dry_run=True,
            )

        mock_employee_filter.assert_not_called()

    @patch(
        "leave_management.management.commands."
        "process_carry_forward_generations.generate_carry_forward_lots"
    )
    @patch(
        "leave_management.management.commands."
        "process_carry_forward_generations.Employee.objects.filter"
    )
    def test_one_employee_failure_does_not_stop_other_employees(
        self,
        mock_employee_filter,
        mock_generate,
    ):
        mock_employee_filter.return_value.order_by.return_value = (
            self.queryset
        )

        mock_generate.side_effect = [
            RuntimeError("Test generation failure"),
            {
                "employee_id": 102,
                "created": 1,
                "skipped": 0,
                "failed": 0,
                "results": [],
            },
        ]

        with self.assertRaises(CommandError):
            self.command.handle(
                date="2026-11-11",
                dry_run=False,
            )

        self.assertEqual(mock_generate.call_count, 2)

        error_output = self.stderr.getvalue()
        self.assertIn("Employee 101 failed", error_output)
        self.assertIn("Test generation failure", error_output)

        output = self.stdout.getvalue()
        self.assertIn("Lots created: 1", output)
        self.assertIn("Failures: 1", output)