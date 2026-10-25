from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from rest_framework.test import APITestCase

from accounts.models import Organization, UserProfile
from leave_management.models import LeaveType


class LeaveTypeManagementAPITests(APITestCase):
    def setUp(self):
        self.organization = Organization.objects.create(
            name="WorkSphere Test Organization",
            code="WTORG",
        )
        self.other_organization = Organization.objects.create(
            name="WorkSphere Other Organization",
            code="WTOUT",
        )

        self.hr_user = self.create_profile_user(
            "leave_type_hr",
            self.organization,
            UserProfile.Role.HR,
        )
        self.admin_user = self.create_profile_user(
            "leave_type_admin",
            self.organization,
            UserProfile.Role.ADMIN,
        )
        self.super_admin_user = self.create_profile_user(
            "leave_type_super_admin",
            self.organization,
            UserProfile.Role.SUPER_ADMIN,
        )
        self.employee_user = self.create_profile_user(
            "leave_type_employee",
            self.organization,
            UserProfile.Role.EMPLOYEE,
        )
        self.other_hr_user = self.create_profile_user(
            "leave_type_other_hr",
            self.other_organization,
            UserProfile.Role.HR,
        )

        self.list_url = "/api/leaves/types/"
        self.policy_url = "/api/leaves/types/management-policy/"

    def create_profile_user(self, username, organization, role):
        user = get_user_model().objects.create_user(
            username=username,
            email=f"{username}@example.com",
            password="TestOnly-Valid-123!",
        )
        UserProfile.objects.create(
            user=user,
            organization=organization,
            role=role,
        )
        return user

    def create_leave_type(
        self,
        organization=None,
        code="ANNUAL",
        name="Annual Leave",
        is_active=True,
    ):
        return LeaveType.objects.create(
            organization=organization or self.organization,
            code=code,
            name=name,
            is_paid=True,
            is_active=is_active,
        )

    def grant_permissions(self, **permissions):
        self.client.force_authenticate(user=self.super_admin_user)

        response = self.client.patch(
            self.policy_url,
            permissions,
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.data)
        self.client.force_authenticate(user=None)

        return response

    def test_super_admin_can_create_without_additional_grant(self):
        self.client.force_authenticate(user=self.super_admin_user)

        response = self.client.post(
            self.list_url,
            {
                "code": "PATERNITY",
                "name": "Paternity Leave",
                "is_paid": True,
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201, response.data)

    def test_hr_cannot_create_without_grant(self):
        self.client.force_authenticate(user=self.hr_user)

        response = self.client.post(
            self.list_url,
            {"code": "SICK", "name": "Sick Leave"},
            format="json",
        )

        self.assertEqual(response.status_code, 403)
        self.assertFalse(
            LeaveType.objects.filter(
                organization=self.organization,
                code="SICK",
            ).exists()
        )

    def test_admin_cannot_create_without_grant(self):
        self.client.force_authenticate(user=self.admin_user)

        response = self.client.post(
            self.list_url,
            {"code": "CASUAL", "name": "Casual Leave"},
            format="json",
        )

        self.assertEqual(response.status_code, 403)
        self.assertFalse(
            LeaveType.objects.filter(
                organization=self.organization,
                code="CASUAL",
            ).exists()
        )

    def test_employee_cannot_create_leave_type(self):
        self.client.force_authenticate(user=self.employee_user)

        employee = SimpleNamespace(
            organization_id=self.organization.pk,
            organization=self.organization,
        )

        with patch(
            "leave_management.views.get_employee_for_user",
            return_value=employee,
        ):
            response = self.client.post(
                self.list_url,
                {"code": "SICK", "name": "Sick Leave"},
                format="json",
            )

        self.assertEqual(response.status_code, 403)
        self.assertFalse(
            LeaveType.objects.filter(
                organization=self.organization,
                code="SICK",
            ).exists()
        )

    def test_super_admin_can_grant_hr_and_hr_can_create(self):
        self.grant_permissions(allow_hr_manage_leave_types=True)

        self.client.force_authenticate(user=self.hr_user)
        response = self.client.post(
            self.list_url,
            {"code": "SICK", "name": "Sick Leave"},
            format="json",
        )

        self.assertEqual(response.status_code, 201, response.data)

    def test_super_admin_can_grant_admin_and_admin_can_create(self):
        self.grant_permissions(allow_admin_manage_leave_types=True)

        self.client.force_authenticate(user=self.admin_user)
        response = self.client.post(
            self.list_url,
            {"code": "CASUAL", "name": "Casual Leave"},
            format="json",
        )

        self.assertEqual(response.status_code, 201, response.data)

        # Admin permission must not automatically grant HR permission.
        self.client.force_authenticate(user=self.hr_user)
        response = self.client.post(
            self.list_url,
            {"code": "SICK", "name": "Sick Leave"},
            format="json",
        )
        self.assertEqual(response.status_code, 403)

    def test_hr_without_grant_sees_only_active_types(self):
        active = self.create_leave_type(code="ANNUAL")
        inactive = self.create_leave_type(
            code="OLD",
            name="Old Leave",
            is_active=False,
        )

        self.client.force_authenticate(user=self.hr_user)
        response = self.client.get(self.list_url)

        self.assertEqual(response.status_code, 200)
        returned_ids = {item["id"] for item in response.data}
        self.assertEqual(returned_ids, {active.pk})
        self.assertNotIn(inactive.pk, returned_ids)

    def test_hr_can_see_inactive_types_after_grant(self):
        active = self.create_leave_type(code="ANNUAL")
        inactive = self.create_leave_type(
            code="OLD",
            name="Old Leave",
            is_active=False,
        )
        self.grant_permissions(allow_hr_manage_leave_types=True)

        self.client.force_authenticate(user=self.hr_user)
        response = self.client.get(self.list_url)

        self.assertEqual(response.status_code, 200)
        returned_ids = {item["id"] for item in response.data}
        self.assertIn(active.pk, returned_ids)
        self.assertIn(inactive.pk, returned_ids)

    def test_hr_can_update_and_deactivate_after_grant(self):
        leave_type = self.create_leave_type()
        self.grant_permissions(allow_hr_manage_leave_types=True)

        self.client.force_authenticate(user=self.hr_user)

        # First request changes the leave type.
        response = self.client.patch(
            f"{self.list_url}{leave_type.pk}/",
            {"name": "Annual Leave Updated", "is_active": False},
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(
            response.data["message"],
            "Leave type updated successfully.",
        )

        leave_type.refresh_from_db()
        self.assertEqual(leave_type.name, "Annual Leave Updated")
        self.assertFalse(leave_type.is_active)

        # Repeating the same deactivation should not save an unnecessary
        # update or claim that the record was changed again.
        response = self.client.patch(
            f"{self.list_url}{leave_type.pk}/",
            {"is_active": False},
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(
            response.data["message"],
            (
                "No changes were needed. The leave type "
                "already has the requested values."
            ),
        )
        self.assertFalse(response.data["leave_type"]["is_active"])

    def test_hr_cannot_modify_without_grant(self):
        leave_type = self.create_leave_type()

        self.client.force_authenticate(user=self.hr_user)
        response = self.client.patch(
            f"{self.list_url}{leave_type.pk}/",
            {"is_active": False},
            format="json",
        )

        self.assertEqual(response.status_code, 403)

        leave_type.refresh_from_db()
        self.assertTrue(leave_type.is_active)

    def test_other_organization_cannot_update_leave_type(self):
        leave_type = self.create_leave_type()

        # The other organization's HR can manage its own leave types.
        # It still cannot access a leave type belonging to this organization.
        self.other_organization.allow_hr_manage_leave_types = True
        self.other_organization.save(
            update_fields=["allow_hr_manage_leave_types", "updated_at"]
        )

        self.client.force_authenticate(user=self.other_hr_user)
        response = self.client.patch(
            f"{self.list_url}{leave_type.pk}/",
            {"name": "Unauthorized Change"},
            format="json",
        )

        self.assertEqual(response.status_code, 404)

        leave_type.refresh_from_db()
        self.assertEqual(leave_type.name, "Annual Leave")

    def test_duplicate_code_is_rejected_case_insensitively(self):
        self.create_leave_type(code="ANNUAL")
        self.grant_permissions(allow_hr_manage_leave_types=True)

        self.client.force_authenticate(user=self.hr_user)
        response = self.client.post(
            self.list_url,
            {"code": "annual", "name": "Another Annual Leave"},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            LeaveType.objects.filter(
                organization=self.organization,
            ).count(),
            1,
        )

    def test_non_super_admin_cannot_change_management_policy(self):
        self.client.force_authenticate(user=self.hr_user)

        response = self.client.patch(
            self.policy_url,
            {"allow_hr_manage_leave_types": True},
            format="json",
        )

        self.assertEqual(response.status_code, 403)

        self.organization.refresh_from_db()
        self.assertFalse(self.organization.allow_hr_manage_leave_types)

    def test_super_admin_can_read_management_policy(self):
        self.client.force_authenticate(user=self.super_admin_user)

        response = self.client.get(self.policy_url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.data["organization"],
            self.organization.code,
        )
        self.assertFalse(response.data["allow_admin_manage_leave_types"])
        self.assertFalse(response.data["allow_hr_manage_leave_types"])

    def test_unauthenticated_user_cannot_manage_leave_types(self):
        self.client.force_authenticate(user=None)

        response = self.client.post(
            self.list_url,
            {"code": "SICK", "name": "Sick Leave"},
            format="json",
        )

        self.assertIn(response.status_code, (401, 403))
