from datetime import date
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.test import TestCase

from employees.models import Employee

from leave_management.models import LeaveRequest
from leave_management.services import (
    create_leave_request,
    decide_leave_request,
)


class LeaveRequestServiceTests(TestCase):
    def setUp(self):
        self.employee = SimpleNamespace(
            pk=12,
            id=12,
            first_name="Test",
            last_name="Employee",
            organization_id=1,
            status=Employee.Status.ACTIVE,
            employee_id="WSMYS2026007",
            department_id=4,
            designation_id=6,
            user_id=8,
            user=SimpleNamespace(is_active=True),
            manager_id=99,
        )

        self.manager = SimpleNamespace(
            pk=99,
            id=99,
            user=SimpleNamespace(is_active=True),
        )

        self.leave_type = SimpleNamespace(
            pk=3,
            id=3,
            organization_id=1,
            name="Annual Leave",
            is_active=True,
        )

        self.policy = SimpleNamespace()

        self.record = SimpleNamespace(
            pk=50,
            id=50,
            employee=self.employee,
            organization_id=1,
            leave_type=self.leave_type,
            manager_at_request=self.manager,
            status=LeaveRequest.Status.PENDING,
            start_date=date(2026, 10, 15),
            end_date=date(2026, 10, 15),
            working_days_count=1,
            reason="Testing",
            save=Mock(),
        )
        self.record.manager_at_request_id = self.manager.pk

    def valid_creation_patches(self):
        patches = [
            patch("leave_management.services._require_active_employee"),
            patch(
                "leave_management.services.local_today",
                return_value=date(2026, 10, 14),
            ),
            patch(
                "leave_management.services.get_attendance_policy",
                return_value=self.policy,
            ),
            patch(
                "leave_management.services._validate_manager_assignment",
                return_value=self.manager,
            ),
            patch(
                "leave_management.services._working_dates",
                return_value=[date(2026, 10, 15)],
            ),
        ]

        started = [item.start() for item in patches]
        self.addCleanup(
            lambda: [item.stop() for item in reversed(patches)]
        )
        return started

    def test_end_date_before_start_date_is_rejected(self):
        with patch("leave_management.services._require_active_employee"):
            with self.assertRaisesRegex(
                ValueError,
                "end date cannot be earlier",
            ):
                create_leave_request(
                    self.employee,
                    self.leave_type,
                    date(2026, 10, 16),
                    date(2026, 10, 15),
                    "Testing",
                )

    def test_past_leave_request_is_rejected(self):
        self.valid_creation_patches()

        with self.assertRaisesRegex(ValueError, "cannot start in the past"):
            create_leave_request(
                self.employee,
                self.leave_type,
                date(2026, 10, 13),
                date(2026, 10, 15),
                "Testing",
            )

    def test_missing_manager_rejects_request(self):
        with (
            patch("leave_management.services._require_active_employee"),
            patch(
                "leave_management.services.local_today",
                return_value=date(2026, 10, 14),
            ),
            patch(
                "leave_management.services._validate_manager_assignment",
                side_effect=ValueError(
                    "A manager must be assigned before requesting WFH."
                ),
            ),
        ):
            with self.assertRaisesRegex(
                ValueError,
                "manager must be assigned",
            ):
                create_leave_request(
                    self.employee,
                    self.leave_type,
                    date(2026, 10, 15),
                    date(2026, 10, 15),
                    "Testing",
                )

    def test_valid_request_copies_department_and_designation(self):
        self.valid_creation_patches()

        with (
            patch(
                "leave_management.services.LeaveRequest.objects.select_for_update"
            ) as select_for_update,
            patch(
                "leave_management.services.LeaveRequest.objects.create",
                return_value=self.record,
            ) as create_record,
        ):
            select_for_update.return_value.filter.return_value.exists.return_value = (
                False
            )

            result = create_leave_request(
                self.employee,
                self.leave_type,
                date(2026, 10, 15),
                date(2026, 10, 15),
                "Testing",
            )

        self.assertIs(result, self.record)
        kwargs = create_record.call_args.kwargs
        self.assertEqual(kwargs["department_id_snapshot"], 4)
        self.assertEqual(kwargs["designation_id_snapshot"], 6)
        self.assertEqual(kwargs["working_days_count"], 1)
        self.assertEqual(kwargs["status"], LeaveRequest.Status.PENDING)

    def test_overlapping_request_is_rejected(self):
        self.valid_creation_patches()

        with (
            patch(
                "leave_management.services.LeaveRequest.objects.select_for_update"
            ) as select_for_update,
            patch(
                "leave_management.services.LeaveRequest.objects.create"
            ) as create_record,
        ):
            select_for_update.return_value.filter.return_value.exists.return_value = (
                True
            )

            with self.assertRaisesRegex(ValueError, "overlaps"):
                create_leave_request(
                    self.employee,
                    self.leave_type,
                    date(2026, 10, 15),
                    date(2026, 10, 15),
                    "Testing",
                )

        create_record.assert_not_called()


class LeaveDecisionServiceTests(TestCase):
    def setUp(self):
        self.manager = SimpleNamespace(
            pk=99,
            id=99,
            organization_id=1,
            user=SimpleNamespace(
                pk=99,
                email="manager@example.com",
            ),
        )

        self.employee = SimpleNamespace(
            pk=12,
            organization_id=1,
            user=SimpleNamespace(
                pk=12,
                email="employee@example.com",
            ),
        )

        self.leave_request = SimpleNamespace(
            pk=50,
            id=50,
            organization_id=1,
            employee=self.employee,
            leave_type=SimpleNamespace(name="Annual Leave"),
            manager_at_request_id=99,
            start_date=date(2026, 10, 20),
            end_date=date(2026, 10, 21),
            status=LeaveRequest.Status.PENDING,
            reviewed_by=None,
            reviewed_at=None,
            review_remarks="",
            save=Mock(),
        )

    def mock_request_lookup(self):
        lookup_patch = patch(
            "leave_management.services.LeaveRequest.objects.select_for_update"
        )
        queryset = lookup_patch.start()
        self.addCleanup(lookup_patch.stop)

        queryset.return_value.select_related.return_value.get.return_value = (
            self.leave_request
        )
        return queryset

    def test_unassigned_manager_cannot_approve(self):
        self.mock_request_lookup()
        self.leave_request.manager_at_request_id = 20

        with self.assertRaisesRegex(
            PermissionError,
            "assigned manager",
        ):
            decide_leave_request(
                50,
                self.manager,
                LeaveRequest.Status.APPROVED,
            )

        self.leave_request.save.assert_not_called()

    def test_ineligible_manager_cannot_approve(self):
        self.mock_request_lookup()
        self.leave_request.manager_at_request_id = self.manager.pk

        with patch(
            "leave_management.services._validate_manager_eligibility",
            side_effect=PermissionError("Manager is not eligible."),
        ):
            with self.assertRaisesRegex(
                PermissionError,
                "Manager is not eligible",
            ):
                decide_leave_request(
                    50,
                    self.manager,
                    LeaveRequest.Status.APPROVED,
                )

        self.leave_request.save.assert_not_called()

    def test_assigned_eligible_manager_can_approve(self):
        self.mock_request_lookup()
        self.leave_request.manager_at_request_id = self.manager.pk

        with patch(
            "leave_management.services._validate_manager_eligibility"
        ):
            result = decide_leave_request(
                50,
                self.manager,
                LeaveRequest.Status.APPROVED,
                "Approved for testing.",
            )

        self.assertIs(result, self.leave_request)
        self.assertEqual(
            self.leave_request.status,
            LeaveRequest.Status.APPROVED,
        )
        self.assertEqual(
            self.leave_request.review_remarks,
            "Approved for testing.",
        )
        self.leave_request.save.assert_called_once()