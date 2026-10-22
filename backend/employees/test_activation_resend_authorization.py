from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from accounts.models import UserProfile
from employees.services import can_manage_employee_activation


class EmployeeActivationResendAuthorizationTests(SimpleTestCase):
    def setUp(self):
        self.employee = SimpleNamespace(
            organization_id=1,
            department_id=4,
        )

    def make_user(self, role, organization_id=1):
        profile = SimpleNamespace(
            role=role,
            organization_id=organization_id,
        )

        return SimpleNamespace(
            is_authenticated=True,
            worksphere_profile=profile,
        )

    def test_employee_cannot_resend_activation_link(self):
        user = self.make_user(UserProfile.Role.EMPLOYEE)

        self.assertFalse(
            can_manage_employee_activation(
                self.employee,
                user,
            )
        )

    def test_same_organization_admin_can_resend_activation_link(self):
        user = self.make_user(UserProfile.Role.ADMIN)

        self.assertTrue(
            can_manage_employee_activation(
                self.employee,
                user,
            )
        )

    def test_admin_from_another_organization_is_denied(self):
        user = self.make_user(
            UserProfile.Role.ADMIN,
            organization_id=2,
        )

        self.assertFalse(
            can_manage_employee_activation(
                self.employee,
                user,
            )
        )

    def test_assigned_hr_can_resend_activation_link(self):
        user = self.make_user(UserProfile.Role.HR)

        with patch(
            "employees.services.DepartmentApprover.objects.filter"
        ) as approver_query:
            approver_query.return_value.exists.return_value = True

            self.assertTrue(
                can_manage_employee_activation(
                    self.employee,
                    user,
                )
            )

    def test_unassigned_hr_cannot_resend_activation_link(self):
        user = self.make_user(UserProfile.Role.HR)

        with patch(
            "employees.services.DepartmentApprover.objects.filter"
        ) as approver_query:
            approver_query.return_value.exists.return_value = False

            self.assertFalse(
                can_manage_employee_activation(
                    self.employee,
                    user,
                )
            )