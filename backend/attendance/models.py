from datetime import time

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import F, Q


def default_working_days():
    # Monday=0 through Sunday=6.
    return [0, 1, 2, 3, 4]


class AttendancePolicy(models.Model):
    class AuditDetailLevel(models.TextChoices):
        SUMMARY = "SUMMARY", "Summary"
        DETAILED = "DETAILED", "Detailed"

    class ArchiveGrouping(models.TextChoices):
        MONTHLY = "MONTHLY", "Monthly"
        YEARLY = "YEARLY", "Yearly"

    organization = models.OneToOneField(
        "accounts.Organization",
        on_delete=models.PROTECT,
        related_name="attendance_policy",
    )

    timezone_name = models.CharField(
        max_length=64,
        default="Asia/Kolkata",
    )

    work_start_time = models.TimeField(default=time(9, 30))
    work_end_time = models.TimeField(default=time(18, 30))
    working_days = models.JSONField(default=default_working_days)

    grace_minutes = models.PositiveSmallIntegerField(default=15)

    consecutive_late_absence_threshold = models.PositiveSmallIntegerField(
        default=3
    )
    consecutive_late_absence_enabled = models.BooleanField(default=True)

    # Same-day WFH
    allow_same_day_wfh = models.BooleanField(default=True)
    same_day_wfh_start_time = models.TimeField(default=time(18, 30))
    same_day_wfh_cutoff_time = models.TimeField(default=time(23, 59))

    # Planned WFH
    allow_planned_wfh = models.BooleanField(default=True)

    # Incomplete checkout: our agreed configurable Option C
    incomplete_checkout_enabled = models.BooleanField(default=True)
    incomplete_checkout_grace_minutes = models.PositiveSmallIntegerField(
        default=15
    )
    incomplete_checkout_auto_mark_incomplete = models.BooleanField(
        default=True
    )
    incomplete_checkout_requires_manager_review = models.BooleanField(
        default=True
    )

    # Reminders
    forgot_to_apply_wfh_reminder_enabled = models.BooleanField(default=True)
    forgot_to_apply_wfh_reminder_before_cutoff_hours = (
        models.PositiveSmallIntegerField(default=2)
    )
    auto_mark_absent_after_wfh_cutoff = models.BooleanField(default=False)
    incomplete_checkout_reminder_enabled = models.BooleanField(default=True)

    # Notifications
    notifications_enabled = models.BooleanField(default=True)
    in_app_notifications_enabled = models.BooleanField(default=True)
    email_notifications_enabled = models.BooleanField(default=True)
    notify_on_wfh_request = models.BooleanField(default=True)
    notify_on_wfh_decision = models.BooleanField(default=True)

    # Audit configuration
    audit_logging_enabled = models.BooleanField(default=True)
    audit_detail_level = models.CharField(
        max_length=10,
        choices=AuditDetailLevel.choices,
        default=AuditDetailLevel.DETAILED,
    )
    audit_retention_days = models.PositiveIntegerField(
        null=True,
        blank=True,
        default=None,
    )

    # Archiving remains disabled until the organization chooses a period.
    archive_after_months = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        default=None,
    )
    archive_grouping = models.CharField(
        max_length=10,
        choices=ArchiveGrouping.choices,
        default=ArchiveGrouping.MONTHLY,
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="attendance_policies_created",
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="attendance_policies_updated",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def clean(self):
        super().clean()

        if (
            self.work_start_time
            and self.work_end_time
            and self.work_end_time <= self.work_start_time
        ):
            raise ValidationError({
                "work_end_time": (
                    "Work end time must be later than work start time. "
                    "Overnight shifts are not supported in this version."
                )
            })

        if (
            self.work_end_time
            and self.same_day_wfh_start_time
            and self.same_day_wfh_start_time < self.work_end_time
        ):
            raise ValidationError({
                "same_day_wfh_start_time": (
                    "Same-day WFH must open at or after normal work end time."
                )
            })

        if (
            self.same_day_wfh_start_time
            and self.same_day_wfh_cutoff_time
            and self.same_day_wfh_cutoff_time
            < self.same_day_wfh_start_time
        ):
            raise ValidationError({
                "same_day_wfh_cutoff_time": (
                    "The same-day WFH cutoff cannot be earlier than "
                    "its opening time."
                )
            })
        if self.forgot_to_apply_wfh_reminder_before_cutoff_hours < 1:
            raise ValidationError({
                "forgot_to_apply_wfh_reminder_before_cutoff_hours": (
                    "The WFH reminder must be at least one hour "
                    "before the deadline."
                )
            })

        if (
            self.forgot_to_apply_wfh_reminder_enabled
            and self.allow_same_day_wfh
            and self.same_day_wfh_start_time
            and self.same_day_wfh_cutoff_time
        ):
            window_minutes = (
                self.same_day_wfh_cutoff_time.hour * 60
                + self.same_day_wfh_cutoff_time.minute
                - self.same_day_wfh_start_time.hour * 60
                - self.same_day_wfh_start_time.minute
            )
            reminder_lead_minutes = (
                self.forgot_to_apply_wfh_reminder_before_cutoff_hours * 60
            )

            if reminder_lead_minutes > window_minutes:
                raise ValidationError({
                    "forgot_to_apply_wfh_reminder_before_cutoff_hours": (
                        "The reminder lead time must fit within the "
                        "same-day WFH application window."
                    )
                })

        if not isinstance(self.working_days, list):
            raise ValidationError({
                "working_days": (
                    "Working days must be a list of weekday numbers."
                )
            })

        if any(
            not isinstance(day, int)
            or isinstance(day, bool)
            or day not in range(7)
            for day in self.working_days
        ):
            raise ValidationError({
                "working_days": (
                    "Use weekday numbers from 0 (Monday) to 6 (Sunday)."
                )
            })

        if len(set(self.working_days)) != len(self.working_days):
            raise ValidationError({
                "working_days": "A weekday cannot appear more than once."
            })

        if (
            self.consecutive_late_absence_enabled
            and self.consecutive_late_absence_threshold < 1
        ):
            raise ValidationError({
                "consecutive_late_absence_threshold": (
                    "The threshold must be at least 1."
                )
            })

        if (
            self.incomplete_checkout_enabled
            and not self.incomplete_checkout_auto_mark_incomplete
            and not self.incomplete_checkout_requires_manager_review
        ):
            raise ValidationError({
                "incomplete_checkout_auto_mark_incomplete": (
                    "When incomplete checkout handling is enabled, either "
                    "auto-marking or manager review must be enabled."
                )
            })

    def __str__(self):
        return f"Attendance Policy - {self.organization.code}"


class Holiday(models.Model):
    organization = models.ForeignKey(
        "accounts.Organization",
        on_delete=models.PROTECT,
        related_name="attendance_holidays",
    )
    date = models.DateField()
    name = models.CharField(max_length=150)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="attendance_holidays_created",
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="attendance_holidays_updated",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "date"],
                name="uniq_holiday_org_date",
            )
        ]
        ordering = ["date", "name"]

    def __str__(self):
        return f"{self.date} - {self.name}"


class AttendanceRecord(models.Model):
    class Status(models.TextChoices):
        PRESENT = "PRESENT", "Present"
        LATE = "LATE", "Late"
        ABSENT = "ABSENT", "Absent"
        WFH = "WFH", "Work From Home"
        INCOMPLETE = "INCOMPLETE", "Incomplete"

    class Source(models.TextChoices):
        BIOMETRIC = "BIOMETRIC", "Biometric"
        COMPANY_SYSTEM = "COMPANY_SYSTEM", "Company Attendance System"
        WORKSPHERE = "WORKSPHERE", "WorkSphere"
        INTEGRATION = "INTEGRATION", "External Integration"
        WFH = "WFH", "Approved Work From Home"

    employee = models.ForeignKey(
        "employees.Employee",
        on_delete=models.PROTECT,
        related_name="attendance_records",
    )

    attendance_date = models.DateField()
    check_in_at = models.DateTimeField(null=True, blank=True)
    check_out_at = models.DateTimeField(null=True, blank=True)

    status = models.CharField(max_length=20, choices=Status.choices)
    source = models.CharField(
        max_length=20,
        choices=Source.choices,
        default=Source.WORKSPHERE,
    )
    source_reference = models.CharField(max_length=150, blank=True)

    # Store relevant policy values used when this record was created.
    policy_snapshot = models.JSONField(default=dict, blank=True)
    remarks = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["employee", "attendance_date"],
                name="uniq_attendance_employee_date",
            ),
            models.CheckConstraint(
                condition=(
                    Q(check_out_at__isnull=True)
                    | (
                        Q(check_in_at__isnull=False)
                        & Q(check_out_at__gte=F("check_in_at"))
                    )
                ),
                name="attendance_checkout_valid",
            ),
        ]
        indexes = [
            models.Index(
                fields=["employee", "attendance_date"],
                name="attendance_employee_date_idx",
            ),
            models.Index(
                fields=["status", "attendance_date"],
                name="attendance_status_date_idx",
            ),
        ]
        ordering = ["-attendance_date"]

    def __str__(self):
        return f"{self.employee} - {self.attendance_date} - {self.status}"


class WFHRequest(models.Model):
    class RequestType(models.TextChoices):
        SAME_DAY = "SAME_DAY", "Same Day"
        PLANNED = "PLANNED", "Planned"

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        APPROVED = "APPROVED", "Approved"
        REJECTED = "REJECTED", "Rejected"

    employee = models.ForeignKey(
        "employees.Employee",
        on_delete=models.PROTECT,
        related_name="wfh_requests",
    )

    # Snapshot the manager assignment when the employee submits the request.
    manager_at_request = models.ForeignKey(
        "employees.Employee",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="wfh_requests_assigned_to_review",
    )

    request_type = models.CharField(
        max_length=20,
        choices=RequestType.choices,
    )
    start_date = models.DateField()
    end_date = models.DateField()
    reason = models.TextField()

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
    )

    requested_at = models.DateTimeField(auto_now_add=True)

    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="wfh_requests_reviewed",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_remarks = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=Q(end_date__gte=F("start_date")),
                name="wfh_end_on_or_after_start",
            )
        ]
        indexes = [
            models.Index(
                fields=["employee", "start_date"],
                name="wfh_employee_start_idx",
            ),
            models.Index(
                fields=["status", "start_date"],
                name="wfh_status_start_idx",
            ),
        ]
        ordering = ["-requested_at"]

    def __str__(self):
        return (
            f"{self.employee} - {self.start_date} to "
            f"{self.end_date} - {self.status}"
        )


class AttendanceAuditLog(models.Model):
    class EventType(models.TextChoices):
        CHECK_IN = "CHECK_IN", "Check In"
        CHECK_OUT = "CHECK_OUT", "Check Out"
        ATTENDANCE_CHANGED = (
            "ATTENDANCE_CHANGED",
            "Attendance Changed",
        )
        WFH_REQUEST_CREATED = (
            "WFH_REQUEST_CREATED",
            "WFH Request Created",
        )
        WFH_REQUEST_APPROVED = (
            "WFH_REQUEST_APPROVED",
            "WFH Request Approved",
        )
        WFH_REQUEST_REJECTED = (
            "WFH_REQUEST_REJECTED",
            "WFH Request Rejected",
        )
        POLICY_CHANGED = "POLICY_CHANGED", "Attendance Policy Changed"
        HOLIDAY_CREATED = "HOLIDAY_CREATED", "Holiday Created"
        HOLIDAY_CHANGED = "HOLIDAY_CHANGED", "Holiday Changed"
        ATTENDANCE_ARCHIVED = (
            "ATTENDANCE_ARCHIVED",
            "Attendance Archived",
        )
        INCOMPLETE_CHECKOUT_FLAGGED = (
            "INCOMPLETE_CHECKOUT_FLAGGED",
            "Incomplete Checkout Flagged",
        )
        ATTENDANCE_EXCEPTION_RESOLVED = (
            "ATTENDANCE_EXCEPTION_RESOLVED",
            "Attendance Exception Resolved",
        )
        WFH_REMINDER_SENT = (
            "WFH_REMINDER_SENT",
            "WFH Reminder Sent",
        )
        ABSENCE_MARKED = (
            "ABSENCE_MARKED",
            "Absence Marked",
        )

    organization = models.ForeignKey(
        "accounts.Organization",
        on_delete=models.PROTECT,
        related_name="attendance_audit_logs",
    )
    employee = models.ForeignKey(
        "employees.Employee",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="attendance_audit_logs",
    )
    performed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="attendance_audit_logs",
    )

    event_type = models.CharField(
        max_length=40,
        choices=EventType.choices,
    )
    entity_type = models.CharField(max_length=50)
    entity_id = models.PositiveBigIntegerField(null=True, blank=True)

    before_data = models.JSONField(default=dict, blank=True)
    after_data = models.JSONField(default=dict, blank=True)
    details = models.JSONField(default=dict, blank=True)

    occurred_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(
                fields=["organization", "occurred_at"],
                name="att_audit_org_created_idx",
            ),
            models.Index(
                fields=["employee", "occurred_at"],
                name="att_audit_emp_created_idx",
            ),
        ]
        ordering = ["-occurred_at"]

    def __str__(self):
        return (
            f"{self.event_type} - {self.organization.code} - "
            f"{self.occurred_at}"
        )


class ArchivedAttendanceRecord(models.Model):
    organization = models.ForeignKey(
        "accounts.Organization",
        on_delete=models.PROTECT,
        related_name="archived_attendance_records",
    )
    employee = models.ForeignKey(
        "employees.Employee",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="archived_attendance_records",
    )

    employee_id_snapshot = models.CharField(max_length=50)
    employee_name_snapshot = models.CharField(max_length=201)
    attendance_date = models.DateField()
    original_record_id = models.PositiveBigIntegerField()
    archive_period = models.CharField(max_length=7)
    record_snapshot = models.JSONField()

    archived_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "original_record_id"],
                name="uniq_archive_source_record",
            )
        ]
        indexes = [
            models.Index(
                fields=["archive_period", "attendance_date"],
                name="att_archive_period_date_idx",
            )
        ]
        ordering = ["-attendance_date"]

    def __str__(self):
        return (
            f"{self.employee_id_snapshot} - "
            f"{self.attendance_date} - archived"
        )


class AttendanceException(models.Model):
    class Status(models.TextChoices):
        OPEN = "OPEN", "Open"
        RESOLVED = "RESOLVED", "Resolved"

    class Resolution(models.TextChoices):
        CONFIRMED_INCOMPLETE = (
            "CONFIRMED_INCOMPLETE",
            "Confirmed Incomplete Checkout",
        )
        CORRECTED_CHECKOUT = (
            "CORRECTED_CHECKOUT",
            "Checkout Corrected",
        )

    attendance_record = models.OneToOneField(
        AttendanceRecord,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="attendance_exception",
    )
    original_record_id = models.PositiveBigIntegerField()

    organization = models.ForeignKey(
        "accounts.Organization",
        on_delete=models.PROTECT,
        related_name="attendance_exceptions",
    )
    employee = models.ForeignKey(
        "employees.Employee",
        on_delete=models.PROTECT,
        related_name="attendance_exceptions",
    )
    assigned_manager = models.ForeignKey(
        "employees.Employee",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="attendance_exceptions_to_review",
    )

    status = models.CharField(
        max_length=10,
        choices=Status.choices,
        default=Status.OPEN,
    )
    resolution = models.CharField(
        max_length=25,
        choices=Resolution.choices,
        blank=True,
    )

    detected_at = models.DateTimeField(auto_now_add=True)

    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="attendance_exceptions_reviewed",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_notes = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "original_record_id"],
                name="uniq_att_exception_source_record",
            )
        ]
        indexes = [
            models.Index(
                fields=["assigned_manager", "status"],
                name="att_exc_manager_status_idx",
            ),
            models.Index(
                fields=["organization", "status"],
                name="att_exc_org_status_idx",
            ),
        ]
        ordering = ["-detected_at"]

    def __str__(self):
        return (
            f"Attendance Exception #{self.pk} - "
            f"{self.employee} - {self.status}"
        )


class AttendanceReminderLog(models.Model):
    class ReminderType(models.TextChoices):
        WFH_APPLICATION = (
            "WFH_APPLICATION",
            "WFH Application Reminder",
        )

    organization = models.ForeignKey(
        "accounts.Organization",
        on_delete=models.PROTECT,
        related_name="attendance_reminder_logs",
    )
    employee = models.ForeignKey(
        "employees.Employee",
        on_delete=models.PROTECT,
        related_name="attendance_reminder_logs",
    )

    reminder_type = models.CharField(
        max_length=30,
        choices=ReminderType.choices,
    )
    reminder_date = models.DateField()

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["employee", "reminder_type", "reminder_date"],
                name="uniq_att_reminder_employee_type_date",
            )
        ]
        ordering = ["-created_at"]

    def __str__(self):
        return (
            f"{self.employee} - {self.reminder_type} - "
            f"{self.reminder_date}"
        )