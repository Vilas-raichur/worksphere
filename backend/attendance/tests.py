from datetime import time
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase

from rest_framework.test import APIRequestFactory, force_authenticate

from rest_framework import status as drf_status
from django.core.exceptions import ValidationError

from employees.models import Employee
from accounts.models import Organization
from .models import AttendancePolicy

from attendance.views import (
    WFHManagerInboxAPIView,
    AttendanceExceptionManagerInboxAPIView,
)



class AttendancePolicyModelTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.organization = Organization.objects.create(
            name="Attendance Test Organization",
            code="ATTTEST",
        )

    def test_default_policy_is_valid(self):
        policy = AttendancePolicy(
            organization=self.organization
        )
        policy.full_clean()

        self.assertEqual(policy.work_start_time, time(9, 30))
        self.assertEqual(policy.work_end_time, time(18, 30))
        self.assertEqual(policy.grace_minutes, 15)
        self.assertEqual(
            policy.consecutive_late_absence_threshold,
            3,
        )
        self.assertEqual(
            policy.working_days,
            [0, 1, 2, 3, 4],
        )

    def test_end_time_before_start_time_is_rejected(self):
        policy = AttendancePolicy(
            organization=self.organization,
            work_start_time=time(9, 30),
            work_end_time=time(9, 0),
        )

        with self.assertRaises(ValidationError):
            policy.clean()

    def test_same_day_wfh_cannot_start_before_work_end(self):
        policy = AttendancePolicy(
            organization=self.organization,
            work_end_time=time(18, 30),
            same_day_wfh_start_time=time(18, 0),
        )

        with self.assertRaises(ValidationError):
            policy.clean()

    def test_invalid_working_day_is_rejected(self):
        policy = AttendancePolicy(
            organization=self.organization,
            working_days=[0, 1, 7],
        )

        with self.assertRaises(ValidationError):
            policy.clean()

    def test_incomplete_checkout_requires_a_handling_action(self):
        policy = AttendancePolicy(
            organization=self.organization,
            incomplete_checkout_enabled=True,
            incomplete_checkout_auto_mark_incomplete=False,
            incomplete_checkout_requires_manager_review=False,
        )

        with self.assertRaises(ValidationError):
            policy.clean()



class AttendanceManagerInboxPermissionTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(
            username="attendance_inbox_permission_test",
            password="test-password-for-tests-only",
        )

        # Provide every attribute required by the manager-eligibility helper.
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
            wfh_filter.return_value.order_by.return_value = []

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
            exception_filter.return_value.order_by.return_value = []

            response = (
                AttendanceExceptionManagerInboxAPIView.as_view()(request)
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, [])