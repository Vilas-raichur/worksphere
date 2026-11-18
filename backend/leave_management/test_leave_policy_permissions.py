
from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from accounts.models import Organization, UserProfile
from leave_management.models import LeavePolicyManagementPermission
from leave_management.policy_permissions import can_manage_leave_policies


User = get_user_model()


class LeavePolicyPermissionTests(TestCase):
    def setUp(self):
        self.organization = Organization.objects.create(
            name="Permission Test Organization",
            code="LPP_TEST",
        )
        self.other_organization = Organization.objects.create(
            name="Other Permission Test Organization",
            code="LPP_OTHER",
        )

        self.super_admin = self.create_user(
            "policy_super_admin",
            self.organization,
            UserProfile.Role.SUPER_ADMIN,
        )
        self.admin = self.create_user(
            "policy_admin",
            self.organization,
            UserProfile.Role.ADMIN,
        )
        self.other_admin = self.create_user(
            "other_policy_admin",
            self.other_organization,
            UserProfile.Role.ADMIN,
        )

        self.client = APIClient()
        self.list_url = reverse("leave-policy-permissions")

    def create_user(self, username, organization, role):
        user = User.objects.create_user(
            username=username,
            password="TestPassword123!",
        )
        UserProfile.objects.create(
            user=user,
            organization=organization,
            role=role,
        )
        return user

    def test_super_admin_can_grant_and_revoke_permission(self):
        self.client.force_authenticate(user=self.super_admin)

        response = self.client.post(
            self.list_url,
            {"admin_profile_id": self.admin.worksphere_profile.pk},
            format="json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(can_manage_leave_policies(self.admin))

        permission_id = response.data["id"]
        response = self.client.delete(
            reverse(
                "leave-policy-permission-revoke",
                kwargs={"permission_id": permission_id},
            )
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(can_manage_leave_policies(self.admin))

    def test_admin_cannot_grant_permission(self):
        self.client.force_authenticate(user=self.admin)

        response = self.client.post(
            self.list_url,
            {"admin_profile_id": self.admin.worksphere_profile.pk},
            format="json",
        )
        self.assertEqual(response.status_code, 403)

    def test_cross_organization_grant_is_rejected(self):
        self.client.force_authenticate(user=self.super_admin)

        response = self.client.post(
            self.list_url,
            {
                "admin_profile_id": (
                    self.other_admin.worksphere_profile.pk
                )
            },
            format="json",
        )
        self.assertEqual(response.status_code, 400)

    def test_repeated_grant_does_not_duplicate_record(self):
        self.client.force_authenticate(user=self.super_admin)

        payload = {
            "admin_profile_id": self.admin.worksphere_profile.pk
        }

        first = self.client.post(
            self.list_url,
            payload,
            format="json",
        )
        second = self.client.post(
            self.list_url,
            payload,
            format="json",
        )

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(
            LeavePolicyManagementPermission.objects.count(),
            1,
        )

    def test_unauthorized_admin_cannot_manage_policies(self):
        self.assertFalse(can_manage_leave_policies(self.admin))
        self.assertTrue(can_manage_leave_policies(self.super_admin))
