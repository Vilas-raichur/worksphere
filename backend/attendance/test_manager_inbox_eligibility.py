from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase

from rest_framework.test import APIRequestFactory, force_authenticate

from employees.models import Employee
from attendance.views import (
    WFHManagerInboxAPIView,
    AttendanceExceptionManagerInboxAPIView,
)


class ManagerInboxEligibilityTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(
            username="manager_inbox_eligibility_test",
            password="test-only-password",
        )

        self.manager_candidate = SimpleNamespace(
            pk=9999,
            organization_id=9999,
            status=Employee.Status.ACTIVE,
            employee_id="WSMYS2026999",
            user_id=9999,
            user=SimpleNamespace(is_active=True),
        )

        self.factory = APIRequestFactory()

    def authenticated_request(self, path):
        request = self.factory.get(path)
        force_authenticate(request, user=self.user)
        return request

    def test_employee_without_reports_cannot_access_wfh_inbox(self):
        request = self.authenticated_request(
            "/api/attendance/wfh/manager/"
        )

        with (
            patch(
                "attendance.views._employee_or_response",
                return_value=(self.manager_candidate, None),
            ),
            patch("attendance.views.Employee.objects.filter") as employee_filter,
            patch("attendance.views.WFHRequest.objects.filter") as wfh_filter,
        ):
            employee_filter.return_value.exists.return_value = False
            wfh_filter.return_value.exists.return_value = False

            response = WFHManagerInboxAPIView.as_view()(request)

        self.assertEqual(response.status_code, 403)

    def test_employee_without_reports_cannot_access_exception_inbox(self):
        request = self.authenticated_request(
            "/api/attendance/exceptions/manager/"
        )

        with (
            patch(
                "attendance.views._employee_or_response",
                return_value=(self.manager_candidate, None),
            ),
            patch("attendance.views.Employee.objects.filter") as employee_filter,
            patch(
                "attendance.views.AttendanceException.objects.filter"
            ) as exception_filter,
        ):
            employee_filter.return_value.exists.return_value = False
            exception_filter.return_value.exists.return_value = False

            response = (
                AttendanceExceptionManagerInboxAPIView.as_view()(request)
            )

        self.assertEqual(response.status_code, 403)

    def test_ineligible_manager_with_reports_cannot_access_wfh_inbox(self):
        request = self.authenticated_request(
            "/api/attendance/wfh/manager/"
        )

        with (
            patch(
                "attendance.views._employee_or_response",
                return_value=(self.manager_candidate, None),
            ),
            patch("attendance.views.Employee.objects.filter") as employee_filter,
            patch("attendance.views.WFHRequest.objects.filter") as wfh_filter,
            patch(
                "attendance.views._validate_manager_eligibility",
                side_effect=PermissionError("Manager is not eligible."),
            ),
        ):
            employee_filter.return_value.exists.return_value = True
            wfh_filter.return_value.exists.return_value = False

            response = WFHManagerInboxAPIView.as_view()(request)

        self.assertEqual(response.status_code, 403)

    def test_ineligible_manager_with_reports_cannot_access_exception_inbox(self):
        request = self.authenticated_request(
            "/api/attendance/exceptions/manager/"
        )

        with (
            patch(
                "attendance.views._employee_or_response",
                return_value=(self.manager_candidate, None),
            ),
            patch("attendance.views.Employee.objects.filter") as employee_filter,
            patch(
                "attendance.views.AttendanceException.objects.filter"
            ) as exception_filter,
            patch(
                "attendance.views._validate_manager_eligibility",
                side_effect=PermissionError("Manager is not eligible."),
            ),
        ):
            employee_filter.return_value.exists.return_value = True
            exception_filter.return_value.exists.return_value = False

            response = (
                AttendanceExceptionManagerInboxAPIView.as_view()(request)
            )

        self.assertEqual(response.status_code, 403)

    def test_eligible_manager_can_access_empty_wfh_inbox(self):
        request = self.authenticated_request(
            "/api/attendance/wfh/manager/"
        )

        with (
            patch(
                "attendance.views._employee_or_response",
                return_value=(self.manager_candidate, None),
            ),
            patch("attendance.views.Employee.objects.filter") as employee_filter,
            patch("attendance.views.WFHRequest.objects.filter") as wfh_filter,
            patch("attendance.views._validate_manager_eligibility"),
        ):
            employee_filter.return_value.exists.return_value = True

            wfh_queryset = wfh_filter.return_value
            wfh_queryset.exists.return_value = False
            wfh_queryset.order_by.return_value = []

            response = WFHManagerInboxAPIView.as_view()(request)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, [])

    def test_eligible_manager_can_access_empty_exception_inbox(self):
        request = self.authenticated_request(
            "/api/attendance/exceptions/manager/"
        )

        with (
            patch(
                "attendance.views._employee_or_response",
                return_value=(self.manager_candidate, None),
            ),
            patch("attendance.views.Employee.objects.filter") as employee_filter,
            patch(
                "attendance.views.AttendanceException.objects.filter"
            ) as exception_filter,
            patch("attendance.views._validate_manager_eligibility"),
        ):
            employee_filter.return_value.exists.return_value = True

            exception_queryset = exception_filter.return_value
            exception_queryset.exists.return_value = False
            exception_queryset.order_by.return_value = []

            response = (
                AttendanceExceptionManagerInboxAPIView.as_view()(request)
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, [])