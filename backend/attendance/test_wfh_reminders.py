from datetime import datetime, time, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from django.test import SimpleTestCase

from attendance.models import AttendanceRecord


class WFHReminderServiceTests(SimpleTestCase):
    def setUp(self):
        self.zone = ZoneInfo("Asia/Kolkata")

        self.policy = SimpleNamespace(
            organization_id=1,
            timezone_name="Asia/Kolkata",
            allow_same_day_wfh=True,
            same_day_wfh_start_time=time(18, 30),
            same_day_wfh_cutoff_time=time(23, 59),
            forgot_to_apply_wfh_reminder_enabled=True,
            forgot_to_apply_wfh_reminder_before_cutoff_hours=2,
            auto_mark_absent_after_wfh_cutoff=True,
        )

        self.employee = SimpleNamespace(
            pk=11,
            organization_id=1,
            organization=SimpleNamespace(pk=1),
            user=SimpleNamespace(pk=20, is_active=True),
        )

    def _run_reminder(
        self,
        reference_now,
        *,
        attendance_exists=False,
        approved_leave=False,
        active_wfh=False,
        reminder_created=True,
    ):
        policy_rows = MagicMock()
        policy_rows.iterator.return_value = [self.policy]

        employee_rows = MagicMock()
        employee_rows.select_related.return_value = employee_rows
        employee_rows.iterator.return_value = [self.employee]

        with (
            patch(
                "attendance.services.AttendancePolicy.objects.select_related",
                return_value=policy_rows,
            ),
            patch(
                "attendance.services.Employee.objects.filter",
                return_value=employee_rows,
            ),
            patch(
                "attendance.services._is_working_day",
                return_value=True,
            ),
            patch(
                "attendance.services.AttendanceRecord.objects.filter",
            ) as attendance_filter,
            patch(
                "leave_management.models.LeaveRequest.objects.filter",
            ) as leave_filter,
            patch(
                "attendance.services.WFHRequest.objects.filter",
            ) as wfh_filter,
            patch(
                "attendance.services.AttendanceReminderLog.objects.get_or_create",
                return_value=(SimpleNamespace(pk=44), reminder_created),
            ) as reminder_create,
            patch("attendance.services._write_audit"),
            patch("attendance.services._schedule_notification") as notification,
        ):
            attendance_filter.return_value.exists.return_value = attendance_exists
            leave_filter.return_value.exists.return_value = approved_leave
            wfh_filter.return_value.exists.return_value = active_wfh

            from attendance.services import send_forgot_to_apply_wfh_reminders

            result = send_forgot_to_apply_wfh_reminders(reference_now)

        return result, notification, reminder_create

    def test_reminder_contains_company_deadline_and_timezone(self):
        now = datetime(2026, 10, 20, 22, 0, tzinfo=self.zone)

        result, notification, reminder_create = self._run_reminder(now)

        self.assertEqual(result, 1)
        reminder_create.assert_called_once()
        notification.assert_called_once()

        message = notification.call_args.args[4]
        self.assertIn("20 Oct 2026", message)
        self.assertIn("11:59 PM", message)
        self.assertIn("Asia/Kolkata", message)
        self.assertIn("ABSENT", message)

    def test_reminder_is_not_sent_before_reminder_time(self):
        now = datetime(2026, 10, 20, 21, 0, tzinfo=self.zone)

        result, notification, reminder_create = self._run_reminder(now)

        self.assertEqual(result, 0)
        notification.assert_not_called()
        reminder_create.assert_not_called()

    def test_reminder_is_not_sent_at_or_after_cutoff(self):
        now = datetime(2026, 10, 20, 23, 59, tzinfo=self.zone)

        result, notification, reminder_create = self._run_reminder(now)

        self.assertEqual(result, 0)
        notification.assert_not_called()
        reminder_create.assert_not_called()

    def test_existing_attendance_suppresses_reminder(self):
        now = datetime(2026, 10, 20, 22, 0, tzinfo=self.zone)

        result, notification, reminder_create = self._run_reminder(
            now,
            attendance_exists=True,
        )

        self.assertEqual(result, 0)
        notification.assert_not_called()
        reminder_create.assert_not_called()

    def test_approved_leave_suppresses_reminder(self):
        now = datetime(2026, 10, 20, 22, 0, tzinfo=self.zone)

        result, notification, reminder_create = self._run_reminder(
            now,
            approved_leave=True,
        )

        self.assertEqual(result, 0)
        notification.assert_not_called()
        reminder_create.assert_not_called()

    def test_active_wfh_request_suppresses_reminder(self):
        now = datetime(2026, 10, 20, 22, 0, tzinfo=self.zone)

        result, notification, reminder_create = self._run_reminder(
            now,
            active_wfh=True,
        )

        self.assertEqual(result, 0)
        notification.assert_not_called()
        reminder_create.assert_not_called()

    def test_existing_reminder_log_prevents_duplicate(self):
        now = datetime(2026, 10, 20, 22, 0, tzinfo=self.zone)

        result, notification, reminder_create = self._run_reminder(
            now,
            reminder_created=False,
        )

        self.assertEqual(result, 0)
        reminder_create.assert_called_once()
        notification.assert_not_called()


class MissingAttendanceAbsenceTests(SimpleTestCase):
    def setUp(self):
        self.zone = ZoneInfo("Asia/Kolkata")

        self.policy = SimpleNamespace(
            organization_id=1,
            timezone_name="Asia/Kolkata",
            allow_same_day_wfh=True,
            same_day_wfh_cutoff_time=time(23, 59),
            forgot_to_apply_wfh_reminder_enabled=True,
            auto_mark_absent_after_wfh_cutoff=True,
        )

        self.employee = SimpleNamespace(
            pk=11,
            organization_id=1,
            organization=SimpleNamespace(pk=1),
            user=SimpleNamespace(pk=20, is_active=True),
        )

    def _run_absence(
        self,
        reference_now,
        *,
        workday_offset=-1,
        reminder_exists=True,
        attendance_exists=False,
        approved_leave=False,
        active_wfh=False,
        auto_enabled=True,
    ):
        self.policy.auto_mark_absent_after_wfh_cutoff = auto_enabled

        workday = reference_now.date() + timedelta(days=workday_offset)

        policy_rows = MagicMock()
        policy_rows.iterator.return_value = [self.policy]

        employee_rows = MagicMock()
        employee_rows.select_related.return_value = employee_rows
        employee_rows.iterator.return_value = [self.employee]

        with (
            patch(
                "attendance.services.AttendancePolicy.objects.select_related",
                return_value=policy_rows,
            ),
            patch(
                "attendance.services.Employee.objects.filter",
                return_value=employee_rows,
            ),
            patch(
                "attendance.services._is_working_day",
                side_effect=lambda employee, policy, day: day == workday,
            ),
            patch(
                "attendance.services.AttendanceReminderLog.objects.filter",
            ) as reminder_filter,
            patch(
                "attendance.services.AttendanceRecord.objects.filter",
            ) as attendance_filter,
            patch(
                "leave_management.models.LeaveRequest.objects.filter",
            ) as leave_filter,
            patch(
                "attendance.services.WFHRequest.objects.filter",
            ) as wfh_filter,
            patch(
                "attendance.services.AttendanceRecord.objects.get_or_create",
                return_value=(SimpleNamespace(pk=55), True),
            ) as attendance_create,
            patch("attendance.services._policy_snapshot", return_value={}),
            patch("attendance.services._write_audit"),
            patch("attendance.services._schedule_notification") as notification,
        ):
            reminder_filter.return_value.exists.return_value = reminder_exists
            attendance_filter.return_value.exists.return_value = attendance_exists
            leave_filter.return_value.exists.return_value = approved_leave
            wfh_filter.return_value.exists.return_value = active_wfh

            from attendance.services import process_missing_attendance_absences

            result = process_missing_attendance_absences(reference_now)

        return result, attendance_create, notification

    def test_absence_is_created_after_cutoff_after_reminder(self):
        now = datetime(2026, 10, 21, 0, 5, tzinfo=self.zone)

        result, attendance_create, notification = self._run_absence(now)

        self.assertEqual(result, 1)
        attendance_create.assert_called_once()

        defaults = attendance_create.call_args.kwargs["defaults"]
        self.assertEqual(
            defaults["status"],
            AttendanceRecord.Status.ABSENT,
        )

        notification.assert_called_once()
        self.assertEqual(notification.call_args.args[5], "ATTENDANCE")

    def test_absence_is_not_created_before_cutoff(self):
        now = datetime(2026, 10, 20, 22, 0, tzinfo=self.zone)

        result, attendance_create, notification = self._run_absence(
            now,
            workday_offset=0,
        )

        self.assertEqual(result, 0)
        attendance_create.assert_not_called()
        notification.assert_not_called()

    def test_absence_requires_a_reminder_log(self):
        now = datetime(2026, 10, 21, 0, 5, tzinfo=self.zone)

        result, attendance_create, notification = self._run_absence(
            now,
            reminder_exists=False,
        )

        self.assertEqual(result, 0)
        attendance_create.assert_not_called()
        notification.assert_not_called()

    def test_existing_attendance_prevents_absence(self):
        now = datetime(2026, 10, 21, 0, 5, tzinfo=self.zone)

        result, attendance_create, notification = self._run_absence(
            now,
            attendance_exists=True,
        )

        self.assertEqual(result, 0)
        attendance_create.assert_not_called()
        notification.assert_not_called()

    def test_approved_leave_prevents_absence(self):
        now = datetime(2026, 10, 21, 0, 5, tzinfo=self.zone)

        result, attendance_create, notification = self._run_absence(
            now,
            approved_leave=True,
        )

        self.assertEqual(result, 0)
        attendance_create.assert_not_called()
        notification.assert_not_called()

    def test_active_wfh_request_prevents_absence(self):
        now = datetime(2026, 10, 21, 0, 5, tzinfo=self.zone)

        result, attendance_create, notification = self._run_absence(
            now,
            active_wfh=True,
        )

        self.assertEqual(result, 0)
        attendance_create.assert_not_called()
        notification.assert_not_called()

    def test_disabled_auto_absence_setting_prevents_absence(self):
        now = datetime(2026, 10, 21, 0, 5, tzinfo=self.zone)

        result, attendance_create, notification = self._run_absence(
            now,
            auto_enabled=False,
        )

        self.assertEqual(result, 0)
        attendance_create.assert_not_called()
        notification.assert_not_called()