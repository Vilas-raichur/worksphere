from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.test import TestCase

from employees.models import Employee, EmployeeDocument
from employees.services import approve_employee_onboarding


class ApproveEmployeeOnboardingGuardTests(TestCase):
    def make_employee(
        self,
        *,
        account_active=True,
        employee_id=None,
    ):
        return SimpleNamespace(
            status=Employee.Status.PENDING_APPROVAL,
            employee_id=employee_id,
            employee_id_configuration=None,
            organization_id=1,
            user_id=10,
            user=SimpleNamespace(is_active=account_active),
            updated_by=None,
            save=Mock(),
        )

    def test_inactive_account_cannot_receive_permanent_employee_id(self):
        employee = self.make_employee(account_active=False)

        with (
            patch(
                "employees.services.can_approve_employee_onboarding",
                return_value=True,
            ),
            patch(
                "employees.services.generate_employee_id"
            ) as generate_id,
        ):
            with self.assertRaisesRegex(
                ValueError,
                "account must be activated",
            ):
                approve_employee_onboarding(
                    employee,
                    approved_by=object(),
                )

        generate_id.assert_not_called()
        employee.save.assert_not_called()

    def test_approval_is_blocked_when_no_required_document_rules_exist(self):
        employee = self.make_employee(account_active=True)

        with (
            patch(
                "employees.services.can_approve_employee_onboarding",
                return_value=True,
            ),
            patch(
                "employees.services.DocumentRequirement.objects.filter"
            ) as requirements_filter,
            patch(
                "employees.services.generate_employee_id"
            ) as generate_id,
        ):
            requirements_filter.return_value.order_by.return_value = []

            with self.assertRaisesRegex(
                ValueError,
                "no active required document requirements",
            ):
                approve_employee_onboarding(
                    employee,
                    approved_by=object(),
                )

        generate_id.assert_not_called()
        employee.save.assert_not_called()

    def test_approval_is_blocked_when_required_document_is_missing(self):
        employee = self.make_employee(account_active=True)
        requirement = SimpleNamespace(
            id=1,
            code="GOV_ID",
        )

        with (
            patch(
                "employees.services.can_approve_employee_onboarding",
                return_value=True,
            ),
            patch(
                "employees.services.DocumentRequirement.objects.filter"
            ) as requirements_filter,
            patch(
                "employees.services.EmployeeDocument.objects.filter",
                return_value=[],
            ),
            patch(
                "employees.services.generate_employee_id"
            ) as generate_id,
        ):
            requirements_filter.return_value.order_by.return_value = [
                requirement
            ]

            with self.assertRaisesRegex(
                ValueError,
                "GOV_ID",
            ):
                approve_employee_onboarding(
                    employee,
                    approved_by=object(),
                )

        generate_id.assert_not_called()
        employee.save.assert_not_called()

    def test_pending_employee_with_existing_permanent_id_is_blocked(self):
        employee = self.make_employee(
            account_active=True,
            employee_id="WSMYS2026005",
        )

        with (
            patch(
                "employees.services.can_approve_employee_onboarding",
                return_value=True,
            ),
            patch(
                "employees.services.generate_employee_id"
            ) as generate_id,
        ):
            with self.assertRaisesRegex(
                ValueError,
                "already has a permanent Employee ID",
            ):
                approve_employee_onboarding(
                    employee,
                    approved_by=object(),
                )

        generate_id.assert_not_called()
        employee.save.assert_not_called()

    def test_valid_approval_generates_id_after_all_document_checks(self):
        employee = self.make_employee(account_active=True)

        requirement = SimpleNamespace(
            id=1,
            code="GOV_ID",
        )
        verified_document = SimpleNamespace(
            document_requirement_id=1,
            status=EmployeeDocument.Status.VERIFIED,
        )
        configuration = object()

        with (
            patch(
                "employees.services.can_approve_employee_onboarding",
                return_value=True,
            ),
            patch(
                "employees.services.DocumentRequirement.objects.filter"
            ) as requirements_filter,
            patch(
                "employees.services.EmployeeDocument.objects.filter",
                return_value=[verified_document],
            ),
            patch(
                "employees.services.get_active_employee_id_configuration",
                return_value=configuration,
            ),
            patch(
                "employees.services.generate_employee_id",
                return_value="WSMYS2026008",
            ) as generate_id,
        ):
            requirements_filter.return_value.order_by.return_value = [
                requirement
            ]

            result = approve_employee_onboarding(
                employee,
                approved_by=object(),
            )

        self.assertIs(result, employee)
        self.assertEqual(employee.employee_id, "WSMYS2026008")
        self.assertIs(
            employee.employee_id_configuration,
            configuration,
        )
        self.assertEqual(employee.status, Employee.Status.ACTIVE)
        generate_id.assert_called_once_with(employee)
        employee.save.assert_called_once()