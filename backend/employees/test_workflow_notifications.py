from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.test import TestCase

from accounts.models import DocumentRequirement
from employees.models import Employee, EmployeeDocument
from employees.services import (
    approve_employee_onboarding,
    verify_employee_document,
)


class OnboardingWorkflowNotificationTests(TestCase):
    def setUp(self):
        self.employee_user = SimpleNamespace(
            pk=10,
            email="onboarding-employee@example.com",
            is_active=True,
        )

        self.employee = SimpleNamespace(
            pk=20,
            id=20,
            organization_id=1,
            onboarding_reference="ONB-TEST-0001",
            first_name="Test",
            last_name="Employee",
            user_id=10,
            user=self.employee_user,
            status=Employee.Status.ONBOARDING_SUBMITTED,
            employee_id=None,
            employee_id_configuration=None,
            updated_by=None,
            save=Mock(),
        )

        self.hr_user = SimpleNamespace(
            pk=30,
            email="hr@example.com",
        )



    def test_final_onboarding_approval_notifies_employee(self):
        requirement = SimpleNamespace(
            id=1,
            code="GOV_ID",
        )

        verified_document = SimpleNamespace(
            document_requirement_id=1,
            status=EmployeeDocument.Status.VERIFIED,
        )

        employee = self.employee
        employee.status = Employee.Status.PENDING_APPROVAL

        configuration = SimpleNamespace(pk=1)

        with (
            patch(
                "employees.services.can_approve_employee_onboarding",
                return_value=True,
            ),
            patch(
                "employees.services.DocumentRequirement.objects.filter"
            ) as requirement_query,
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
                return_value="WSMYS2026009",
            ),
            patch(
                "employees.services.schedule_notification"
            ) as notify,
        ):
            requirement_query.return_value.order_by.return_value = [
                requirement
            ]

            result = approve_employee_onboarding(
                employee=employee,
                approved_by=self.hr_user,
            )

        self.assertIs(result, employee)
        self.assertEqual(employee.employee_id, "WSMYS2026009")
        self.assertEqual(employee.status, Employee.Status.ACTIVE)

        notify.assert_called_once()
        notification = notify.call_args.kwargs

        self.assertIs(notification["user"], self.employee_user)
        self.assertEqual(notification["category"], "ONBOARDING")
        self.assertIn(
            "WSMYS2026009",
            notification["message"],
        )
