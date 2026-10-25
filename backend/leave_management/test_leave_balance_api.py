from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase
from rest_framework import status
from rest_framework.response import Response
from rest_framework.test import APIRequestFactory, force_authenticate

from leave_management import views


class LeaveBalanceSummaryAPITests(SimpleTestCase):
    def setUp(self):
        self.factory = APIRequestFactory()
        self.user = SimpleNamespace(
            pk=101,
            is_authenticated=True,
        )
        self.employee = SimpleNamespace(pk=12)
        self.view = views.LeaveBalanceSummaryAPIView.as_view()

    def make_request(self):
        request = self.factory.get("/api/leaves/balance/")
        force_authenticate(request, user=self.user)
        return request

    def test_employee_can_get_own_balance_summary(self):
        expected_summary = {
            "balances": [
                {
                    "leave_type": "Annual Leave",
                    "entitled_days": 12,
                    "used_days": 2,
                    "remaining_days": 10,
                }
            ]
        }

        with (
            patch(
                "leave_management.views._employee_or_response",
                return_value=(self.employee, None),
            ),
            patch(
                "leave_management.views.get_employee_leave_balance_summary",
                return_value=expected_summary,
            ) as summary_mock,
        ):
            response = self.view(self.make_request())

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, expected_summary)
        summary_mock.assert_called_once_with(self.employee)

    def test_employee_lookup_error_is_returned(self):
        error_response = Response(
            {"error": "Employee profile not found."},
            status=status.HTTP_403_FORBIDDEN,
        )

        with (
            patch(
                "leave_management.views._employee_or_response",
                return_value=(None, error_response),
            ),
            patch(
                "leave_management.views.get_employee_leave_balance_summary",
            ) as summary_mock,
        ):
            response = self.view(self.make_request())

        self.assertEqual(
            response.status_code,
            status.HTTP_403_FORBIDDEN,
        )
        summary_mock.assert_not_called()

    def test_service_validation_error_returns_bad_request(self):
        with (
            patch(
                "leave_management.views._employee_or_response",
                return_value=(self.employee, None),
            ),
            patch(
                "leave_management.views.get_employee_leave_balance_summary",
                side_effect=ValueError("Employee login account must be active."),
            ),
        ):
            response = self.view(self.make_request())

        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST,
        )
        self.assertEqual(
            response.data["error"],
            "Employee login account must be active.",
        )