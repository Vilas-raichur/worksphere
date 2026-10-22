from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import Organization, UserProfile


User = get_user_model()


class EmployeeCreationAuthorizationTests(APITestCase):
    def setUp(self):
        self.organization = Organization.objects.create(
            name="Authorization Test Organization",
            code="AUTHZ",
        )

        self.employee_user = User.objects.create_user(
            username="ONB-AUTHZ-TEST",
            password="TestOnly-Valid-123!",
        )

        UserProfile.objects.create(
            user=self.employee_user,
            organization=self.organization,
            role=UserProfile.Role.EMPLOYEE,
        )

    def test_employee_cannot_create_employee_record(self):
        self.client.force_authenticate(
            user=self.employee_user
        )

        response = self.client.post(
            "/api/employees/create/",
            {},
            format="json",
        )

        self.assertEqual(
            response.status_code,
            status.HTTP_403_FORBIDDEN,
        )

        self.assertEqual(
            response.data["error"],
            (
                "Only HR or Admin users can create "
                "employee onboarding records."
            ),
        )