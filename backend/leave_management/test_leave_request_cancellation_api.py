from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from rest_framework import status
from rest_framework.test import APITestCase

from leave_management.models import LeaveRequest


User = get_user_model()


class LeaveRequestCancellationAPITests(APITestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="leave_cancel_api_test",
            password="TestOnly-Valid-123!",
        )

        self.employee = SimpleNamespace(pk=12)

        self.leave_request = SimpleNamespace(
            pk=50,
            status=LeaveRequest.Status.CANCELLED,
        )

        self.url = "/api/leaves/requests/50/cancel/"

        self.client.force_authenticate(user=self.user)

    def mock_employee_lookup(self):
        employee_patcher = patch(
            "leave_management.views._employee_or_response",
            return_value=(self.employee, None),
        )
        employee_patcher.start()
        self.addCleanup(employee_patcher.stop)

    def test_successful_cancellation_returns_200(self):
        self.mock_employee_lookup()

        with (
            patch(
                "leave_management.views.cancel_leave_request",
                return_value=self.leave_request,
            ) as cancel_service,
            patch(
                "leave_management.views.LeaveRequestReadSerializer"
            ) as read_serializer,
        ):
            read_serializer.return_value.data = {
                "id": 50,
                "status": "CANCELLED",
            }

            response = self.client.post(
                self.url,
                {},
                format="json",
            )

        self.assertEqual(
            response.status_code,
            status.HTTP_200_OK,
        )
        self.assertEqual(
            response.data["leave_request"]["status"],
            "CANCELLED",
        )
        cancel_service.assert_called_once_with(
            leave_request_id=50,
            employee=self.employee,
        )

    def test_missing_request_returns_404(self):
        self.mock_employee_lookup()

        with patch(
            "leave_management.views.cancel_leave_request",
            side_effect=LeaveRequest.DoesNotExist,
        ):
            response = self.client.post(
                self.url,
                {},
                format="json",
            )

        self.assertEqual(
            response.status_code,
            status.HTTP_404_NOT_FOUND,
        )

    def test_unauthorized_cancellation_returns_403(self):
        self.mock_employee_lookup()

        with patch(
            "leave_management.views.cancel_leave_request",
            side_effect=PermissionError(
                "You are not authorized to cancel this leave request."
            ),
        ):
            response = self.client.post(
                self.url,
                {},
                format="json",
            )

        self.assertEqual(
            response.status_code,
            status.HTTP_403_FORBIDDEN,
        )

    def test_non_pending_request_returns_400(self):
        self.mock_employee_lookup()

        with patch(
            "leave_management.views.cancel_leave_request",
            side_effect=ValueError(
                "Only pending leave requests can be cancelled."
            ),
        ):
            response = self.client.post(
                self.url,
                {},
                format="json",
            )

        self.assertEqual(
            response.status_code,
            status.HTTP_400_BAD_REQUEST,
        )