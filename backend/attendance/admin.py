from django.contrib import admin

from .models import (
    AttendancePolicy,
    Holiday,
    AttendanceRecord,
    WFHRequest,
    AttendanceAuditLog,
    ArchivedAttendanceRecord,
    AttendanceException,
    AttendanceReminderLog,
)


@admin.register(AttendancePolicy)
class AttendancePolicyAdmin(admin.ModelAdmin):
    list_display = (
        "organization",
        "work_start_time",
        "work_end_time",
        "grace_minutes",
        "consecutive_late_absence_threshold",
        "allow_same_day_wfh",
        "same_day_wfh_start_time",
        "same_day_wfh_cutoff_time",
        "forgot_to_apply_wfh_reminder_enabled",
        "forgot_to_apply_wfh_reminder_before_cutoff_hours",
        "auto_mark_absent_after_wfh_cutoff",
        "allow_planned_wfh",
        "incomplete_checkout_enabled",
        "audit_logging_enabled",
        "archive_after_months",
    )
    list_filter = (
        "allow_same_day_wfh",
        "allow_planned_wfh",
        "forgot_to_apply_wfh_reminder_enabled",
        "auto_mark_absent_after_wfh_cutoff",
        "incomplete_checkout_enabled",
        "audit_logging_enabled",
        "archive_grouping",
    )
    search_fields = ("organization__name", "organization__code")
    readonly_fields = ("created_at", "updated_at")


@admin.register(Holiday)
class HolidayAdmin(admin.ModelAdmin):
    list_display = ("organization", "date", "name", "is_active")
    list_filter = ("organization", "is_active", "date")
    search_fields = ("organization__name", "organization__code", "name")
    readonly_fields = ("created_at", "updated_at")


@admin.register(AttendanceRecord)
class AttendanceRecordAdmin(admin.ModelAdmin):
    list_display = (
        "employee",
        "attendance_date",
        "check_in_at",
        "check_out_at",
        "status",
        "source",
    )
    list_filter = ("status", "source", "attendance_date")
    search_fields = (
        "employee__employee_id",
        "employee__onboarding_reference",
        "employee__first_name",
        "employee__last_name",
    )
    readonly_fields = ("created_at", "updated_at")


@admin.register(WFHRequest)
class WFHRequestAdmin(admin.ModelAdmin):
    list_display = (
        "employee",
        "manager_at_request",
        "request_type",
        "start_date",
        "end_date",
        "status",
        "reviewed_by",
    )
    list_filter = ("request_type", "status", "start_date")
    search_fields = (
        "employee__employee_id",
        "employee__onboarding_reference",
        "employee__first_name",
        "employee__last_name",
    )
    readonly_fields = ("requested_at", "created_at", "updated_at")


@admin.register(AttendanceAuditLog)
class AttendanceAuditLogAdmin(admin.ModelAdmin):
    list_display = (
        "organization",
        "event_type",
        "entity_type",
        "entity_id",
        "performed_by",
        "occurred_at",
    )
    list_filter = ("organization", "event_type", "occurred_at")
    search_fields = (
        "organization__name",
        "organization__code",
        "employee__employee_id",
        "employee__onboarding_reference",
        "performed_by__username",
    )
    readonly_fields = (
        "organization",
        "employee",
        "performed_by",
        "event_type",
        "entity_type",
        "entity_id",
        "before_data",
        "after_data",
        "details",
        "occurred_at",
    )

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(ArchivedAttendanceRecord)
class ArchivedAttendanceRecordAdmin(admin.ModelAdmin):
    list_display = (
        "organization",
        "employee_id_snapshot",
        "employee_name_snapshot",
        "attendance_date",
        "archive_period",
        "archived_at",
    )
    list_filter = ("organization", "archive_period")
    search_fields = ("employee_id_snapshot", "employee_name_snapshot")
    readonly_fields = (
        "organization",
        "employee",
        "employee_id_snapshot",
        "employee_name_snapshot",
        "attendance_date",
        "original_record_id",
        "archive_period",
        "record_snapshot",
        "archived_at",
    )

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(AttendanceException)
class AttendanceExceptionAdmin(admin.ModelAdmin):
    list_display = (
        "employee",
        "original_record_id",
        "assigned_manager",
        "status",
        "resolution",
        "detected_at",
        "reviewed_by",
    )
    list_filter = ("organization", "status", "resolution")
    search_fields = (
        "employee__employee_id",
        "employee__onboarding_reference",
        "assigned_manager__employee_id",
    )
    readonly_fields = (
        "attendance_record",
        "original_record_id",
        "organization",
        "employee",
        "assigned_manager",
        "status",
        "resolution",
        "detected_at",
        "reviewed_by",
        "reviewed_at",
        "review_notes",
        "created_at",
        "updated_at",
    )

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(AttendanceReminderLog)
class AttendanceReminderLogAdmin(admin.ModelAdmin):
    list_display = (
        "organization",
        "employee",
        "reminder_type",
        "reminder_date",
        "created_at",
    )
    list_filter = ("organization", "reminder_type", "reminder_date")
    search_fields = (
        "employee__employee_id",
        "employee__onboarding_reference",
    )
    readonly_fields = (
        "organization",
        "employee",
        "reminder_type",
        "reminder_date",
        "created_at",
    )

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False