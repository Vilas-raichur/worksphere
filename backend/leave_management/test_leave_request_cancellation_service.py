from types import SimpleNamespace
from unittest.mock import Mock, patch

from datetime import date

from django.test import TestCase

from leave_management.models import LeaveRequest
from leave_management.services import cancel_leave_request


class LeaveRequestCancellationServiceTests(TestCase):
    def setUp(self):
        self.employee = SimpleNamespace(
            pk=12,
            first_name="Test",
            last_name="Employee",
            onboarding_reference="ONB-TEST-001",
        )

        self.manager_user = SimpleNamespace(
            pk=99,
            email="manager@example.com",
        )
        self.manager = SimpleNamespace(user=self.manager_user)

        self.leave_request = SimpleNamespace(
            pk=50,
            employee=self.employee,
            employee_id=12,
            manager_at_request=self.manager,
            organization_id=1,
            leave_type=SimpleNamespace(name="Annual Leave"),
            start_date=date(2026, 11, 2),
            end_date=date(2026, 11, 2),
            status=LeaveRequest.Status.PENDING,
            save=Mock(),
        )

        notification_patcher = patch(
            "leave_management.services.schedule_notification"
        )
        self.schedule_notification = notification_patcher.start()
        self.addCleanup(notification_patcher.stop)

    def mock_request_lookup(self):
        lookup_patch = patch(
            "leave_management.services."
            "LeaveRequest.objects.select_for_update"
        )
        queryset = lookup_patch.start()
        self.addCleanup(lookup_patch.stop)

        queryset.return_value.get.return_value = self.leave_request

        return queryset

    def test_owner_can_cancel_pending_request(self):
        self.mock_request_lookup()

        result = cancel_leave_request(50, self.employee)

        self.assertIs(result, self.leave_request)
        self.assertEqual(
            self.leave_request.status,
            LeaveRequest.Status.CANCELLED,
        )
        self.leave_request.save.assert_called_once_with(
            update_fields=["status", "updated_at"]
        )

    def test_employee_cannot_cancel_another_employees_request(self):
        self.mock_request_lookup()
        self.leave_request.employee_id = 99

        with self.assertRaisesRegex(
            PermissionError,
            "not authorized",
        ):
            cancel_leave_request(50, self.employee)

        self.leave_request.save.assert_not_called()

    def test_approved_request_cannot_be_cancelled(self):
        self.mock_request_lookup()
        self.leave_request.status = LeaveRequest.Status.APPROVED

        with self.assertRaisesRegex(
            ValueError,
            "Only pending",
        ):
            cancel_leave_request(50, self.employee)

        self.leave_request.save.assert_not_called()

    def test_already_cancelled_request_cannot_be_cancelled_again(self):
        self.mock_request_lookup()
        self.leave_request.status = LeaveRequest.Status.CANCELLED

        with self.assertRaisesRegex(
            ValueError,
            "Only pending",
        ):
            cancel_leave_request(50, self.employee)

        self.leave_request.save.assert_not_called()

    def test_missing_request_is_not_silently_ignored(self):
        queryset = self.mock_request_lookup()
        queryset.return_value.get.side_effect = (
            LeaveRequest.DoesNotExist
        )

        with self.assertRaises(LeaveRequest.DoesNotExist):
            cancel_leave_request(999, self.employee)