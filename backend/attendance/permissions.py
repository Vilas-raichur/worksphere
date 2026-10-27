from rest_framework.permissions import BasePermission

from attendance.models import AttendanceException
from attendance.services import _validate_manager_eligibility
from employees.models import Employee


class IsAssignedEligibleAttendanceExceptionManager(BasePermission):
    """
    Allows only the assigned, eligible manager to review an exception.
    """

    message = (
        "Only the assigned, eligible manager may review this exception."
    )

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False

        # Allow DRF to handle unsupported methods such as GET.
        # The exception review itself remains restricted to POST.
        if request.method != "POST":
            return True

        try:
            manager_employee = request.user.employee_record
        except (Employee.DoesNotExist, AttributeError):
            return False

        exception_id = request.data.get("exception_id")

        if not exception_id:
            return False

        exception = (
            AttendanceException.objects
            .select_related("attendance_record__employee")
            .filter(pk=exception_id)
            .first()
        )

        if exception is None:
            return False

        if exception.assigned_manager_id != manager_employee.pk:
            return False

        try:
            _validate_manager_eligibility(
                manager_employee,
                exception.attendance_record.employee.organization_id,
            )
        except (PermissionError, ValueError):
            return False

        return True