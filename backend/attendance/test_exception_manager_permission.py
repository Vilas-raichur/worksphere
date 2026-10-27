from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from rest_framework.test import APIRequestFactory
from rest_framework.views import APIView

from employees.models import Employee
from attendance.permissions import (
    IsAssignedEligibleAttendanceExceptionManager,
)


class AssignedExceptionManagerPermissionTests(SimpleTestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.permission = IsAssignedEligibleAttendanceExceptionManager()

        self.employee = SimpleNamespace(
            pk=20,
            organization_id=1,
            status=Employee.Status.ACTIVE,
            employee_id="WSMYS2026020",
            user_id=20,
            user=SimpleNamespace(is_active=True),
        )

        self.exception = SimpleNamespace(
            assigned_manager_id=20,
            attendance_record=SimpleNamespace(
                employee=SimpleNamespace(organization_id=1)
            ),
        )

    def test_get_does_not_require_post_review_body(self):
        raw_request = self.factory.get(
            "/api/attendance/exceptions/review/"
        )
        request = APIView().initialize_request(raw_request)
        request.user = SimpleNamespace(is_authenticated=True)

        allowed = self.permission.has_permission(request, None)

        self.assertTrue(allowed)

    def make_request(self, employee, exception_id=55):
        raw_request = self.factory.post(
            "/api/attendance/exceptions/review/",
            {"exception_id": exception_id},
            format="json",
        )

        # Convert the factory's Django request into a DRF Request.
        request = APIView().initialize_request(raw_request)

        # Set the authenticated user directly because this test calls the
        # permission class itself rather than going through APIView.dispatch().
        request.user = SimpleNamespace(
            is_authenticated=True,
            employee_record=employee,
        )

        return request

    def mock_exception(self, exception):
        patcher = patch(
            "attendance.permissions.AttendanceException.objects.select_related"
        )
        select_related = patcher.start()
        self.addCleanup(patcher.stop)

        select_related.return_value.filter.return_value.first.return_value = (
            exception
        )

    def test_other_manager_cannot_review_exception(self):
        request = self.make_request(self.employee)
        self.exception.assigned_manager_id = 999
        self.mock_exception(self.exception)

        with patch(
            "attendance.permissions._validate_manager_eligibility"
        ) as eligibility:
            allowed = self.permission.has_permission(request, None)

        self.assertFalse(allowed)
        eligibility.assert_not_called()

    def test_assigned_but_ineligible_manager_is_denied(self):
        request = self.make_request(self.employee)
        self.exception.assigned_manager_id = self.employee.pk
        self.mock_exception(self.exception)

        with patch(
            "attendance.permissions._validate_manager_eligibility",
            side_effect=PermissionError("Manager is not eligible."),
        ):
            allowed = self.permission.has_permission(request, None)

        self.assertFalse(allowed)

    def test_assigned_eligible_manager_is_allowed(self):
        request = self.make_request(self.employee)
        self.exception.assigned_manager_id = self.employee.pk
        self.mock_exception(self.exception)

        with patch(
            "attendance.permissions._validate_manager_eligibility"
        ) as eligibility:
            allowed = self.permission.has_permission(request, None)

        self.assertTrue(allowed)
        eligibility.assert_called_once_with(self.employee, 1)
