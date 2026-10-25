from django.contrib import admin

from leave_management.models import LeaveRequest, LeaveType


@admin.register(LeaveType)
class LeaveTypeAdmin(admin.ModelAdmin):
    list_display = [
        "code",
        "name",
        "organization",
        "is_paid",
        "is_active",
    ]
    list_filter = [
        "organization",
        "is_paid",
        "is_active",
    ]
    search_fields = [
        "code",
        "name",
        "organization__name",
    ]
    list_select_related = ["organization"]


@admin.register(LeaveRequest)
class LeaveRequestAdmin(admin.ModelAdmin):
    list_display = [
        "id",
        "employee",
        "leave_type",
        "start_date",
        "end_date",
        "working_days_count",
        "status",
        "manager_at_request",
        "requested_at",
    ]
    list_filter = [
        "organization",
        "leave_type",
        "status",
        "requested_at",
    ]
    search_fields = [
        "employee__onboarding_reference",
        "employee__employee_id",
        "employee__first_name",
        "employee__last_name",
    ]
    readonly_fields = [
        "employee",
        "organization",
        "leave_type",
        "manager_at_request",
        "department_id_snapshot",
        "designation_id_snapshot",
        "start_date",
        "end_date",
        "working_days_count",
        "reason",
        "requested_at",
    ]
    list_select_related = [
        "employee",
        "leave_type",
        "manager_at_request",
    ]