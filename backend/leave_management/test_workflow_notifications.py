from datetime import date
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.test import TestCase

from employees.models import Employee
from leave_management.models import LeaveRequest
from leave_management.services import (
    create_leave_request,
    decide_leave_request,
    cancel_leave_request,
)


class LeaveWorkflowNotificationTests(TestCase):
    def setUp(self):
        self.employee_user = SimpleNamespace(
            pk=8,
            email="employee@example.com",
        )
        self.manager_user = SimpleNamespace(
            pk=13,
            email="manager@example.com",
        )

        self.employee = SimpleNamespace(
            pk=12,
            id=12,
            organization_id=1,
            status=Employee.Status.ACTIVE,
            employee_id="WSMYS2026007",
            onboarding_reference="ONB-000009",
            first_name="Test",
            last_name="Employee",
            department_id=4,
            designation_id=6,
            user_id=8,
            user=self.employee_user,
            manager_id=99,
        )

        self.manager = SimpleNamespace(
            pk=99,
            id=99,
            user=self.manager_user,
            onboarding_reference="ONB-000010",
        )

        self.leave_type = SimpleNamespace(
            pk=1,
            id=1,
            organization_id=1,
            is_active=True,
            name="Annual Leave",
            code="ANNUAL",
        )

        self.leave_request = SimpleNamespace(
            pk=50,
            id=50,
            employee=self.employee,
            employee_id=12,
            organization_id=1,
            leave_type=self.leave_type,
            manager_at_request=self.manager,
            manager_at_request_id=self.manager.pk,
            status=LeaveRequest.Status.PENDING,
            start_date=date(2026, 10, 20),
            end_date=date(2026, 10, 21),
            working_days_count=2,
            reason="Testing",
            review_remarks="",
            save=Mock(),
        )

    def test_new_leave_request_notifies_assigned_manager(self):
        with (
            patch(
                "leave_management.services._require_active_employee"
            ),
            patch(
                "leave_management.services.local_today",
                return_value=date(2026, 10, 15),
            ),
            patch(
                "leave_management.services.get_attendance_policy",
                return_value=SimpleNamespace(),
            ),
            patch(
                "leave_management.services._validate_manager_assignment",
                return_value=self.manager,
            ),
            patch(
                "leave_management.services._working_dates",
                return_value=[
                    date(2026, 10, 20),
                    date(2026, 10, 21),
                ],
            ),
            patch(
                "leave_management.services.LeaveRequest.objects.select_for_update"
            ) as existing_query,
            patch(
                "leave_management.services.LeaveRequest.objects.create",
                return_value=self.leave_request,
            ),
            patch(
                "leave_management.services.schedule_notification"
            ) as notify,
        ):
            existing_query.return_value.filter.return_value.exists.return_value = (
                False
            )

            result = create_leave_request(
                employee=self.employee,
                leave_type=self.leave_type,
                start_date=date(2026, 10, 20),
                end_date=date(2026, 10, 21),
                reason="Testing notifications.",
            )

        self.assertIs(result, self.leave_request)
        notify.assert_called_once()

        notification = notify.call_args.kwargs

        self.assertIs(notification["user"], self.manager_user)
        self.assertEqual(notification["category"], "LEAVE")
        self.assertEqual(
            notification["metadata"]["event"],
            "leave_request_submitted",
        )

    def _assert_decision_notifies_employee(self, decision):
        self.leave_request.status = LeaveRequest.Status.PENDING
        self.leave_request.review_remarks = ""

        with (
            patch(
                "leave_management.services.LeaveRequest.objects.select_for_update"
            ) as request_query,
            patch(
                "leave_management.services._validate_manager_eligibility"
            ),
            patch(
                "leave_management.services.schedule_notification"
            ) as notify,
        ):
            request_query.return_value.select_related.return_value.get.return_value = (
                self.leave_request
            )

            result = decide_leave_request(
                leave_request_id=self.leave_request.pk,
                reviewer=self.manager,
                decision=decision,
                remarks="Recorded for testing.",
            )

        self.assertIs(result, self.leave_request)
        notify.assert_called_once()

        notification = notify.call_args.kwargs

        self.assertIs(notification["user"], self.employee_user)
        self.assertEqual(notification["category"], "LEAVE")
        self.assertEqual(
            notification["metadata"]["status"],
            decision,
        )
        self.assertIn(
            decision.lower(),
            notification["title"].lower(),
        )
        self.assertIn(
            "Recorded for testing.",
            notification["message"],
        )

    def test_approved_leave_notifies_employee(self):
        self._assert_decision_notifies_employee(
            LeaveRequest.Status.APPROVED
        )

    def test_rejected_leave_notifies_employee(self):
        self._assert_decision_notifies_employee(
            LeaveRequest.Status.REJECTED
        )

    def test_cancelled_leave_notifies_assigned_manager(self):
        with (
            patch(
                "leave_management.services."
                "LeaveRequest.objects.select_for_update"
            ) as request_query,
            patch(
                "leave_management.services.schedule_notification"
            ) as notify,
        ):
            request_query.return_value.get.return_value = (
                self.leave_request
            )

            result = cancel_leave_request(
                leave_request_id=self.leave_request.pk,
                employee=self.employee,
            )

        self.assertIs(result, self.leave_request)
        self.assertEqual(
            self.leave_request.status,
            LeaveRequest.Status.CANCELLED,
        )

        notify.assert_called_once()
        notification = notify.call_args.kwargs

        self.assertIs(notification["user"], self.manager_user)
        self.assertEqual(notification["category"], "LEAVE")
        self.assertEqual(
            notification["metadata"]["event"],
            "leave_request_cancelled",
        )
        self.assertEqual(
            notification["metadata"]["status"],
            LeaveRequest.Status.CANCELLED,
        )
        self.assertIn(
            "Test Employee",
            notification["message"],
        )
