from django.db import transaction
from django.utils import timezone
from notifications.services import schedule_notification

from attendance.services import (
    _require_active_employee,
    _working_dates,
    _validate_manager_assignment,
    _validate_manager_eligibility,
    get_attendance_policy,
    local_today,
)

from leave_management.models import LeaveBalance, LeaveRequest

@transaction.atomic
def create_leave_request(
    employee,
    leave_type,
    start_date,
    end_date,
    reason,
):
    _require_active_employee(employee)

    if end_date < start_date:
        raise ValueError(
            "Leave end date cannot be earlier than the start date."
        )

    if start_date < local_today(employee):
        raise ValueError(
            "Leave requests cannot start in the past."
        )

    if not reason or not reason.strip():
        raise ValueError("A reason is required for leave.")

    if (
        not leave_type.is_active
        or leave_type.organization_id != employee.organization_id
    ):
        raise ValueError(
            "The selected leave type is not active for your organization."
        )

    # Require a currently eligible manager before submitting.
    manager = _validate_manager_assignment(employee)

    policy = get_attendance_policy(employee)
    working_dates = _working_dates(
        employee,
        policy,
        start_date,
        end_date,
    )

    if not working_dates:
        raise ValueError(
            "The requested period contains no configured working days."
        )

    overlapping_request = (
        LeaveRequest.objects.select_for_update()
        .filter(
            employee=employee,
            status__in=[
                LeaveRequest.Status.PENDING,
                LeaveRequest.Status.APPROVED,
            ],
            start_date__lte=end_date,
            end_date__gte=start_date,
        )
        .exists()
    )

    if overlapping_request:
        raise ValueError(
            "An existing pending or approved leave request overlaps "
            "the selected dates."
        )

    leave_request = LeaveRequest.objects.create(
        organization_id=employee.organization_id,
        employee=employee,
        leave_type=leave_type,
        department_id_snapshot=employee.department_id,
        designation_id_snapshot=employee.designation_id,
        manager_at_request=manager,
        start_date=start_date,
        end_date=end_date,
        working_days_count=len(working_dates),
        reason=reason.strip(),
        status=LeaveRequest.Status.PENDING,
    )

    employee_identifier = (
        getattr(employee, "employee_id", None)
        or getattr(employee, "onboarding_reference", None)
        or f"Employee #{employee.pk}"
    )

    employee_name = (
        f"{employee.first_name} {employee.last_name}".strip()
    )

    leave_type_name = leave_type.name.strip()

    leave_label = (
        leave_type_name
        if leave_type_name.casefold().endswith("leave")
        else f"{leave_type_name} leave"
    )

    start_date_label = start_date.strftime("%d %b %Y")
    end_date_label = end_date.strftime("%d %b %Y")

    schedule_notification(
        user=manager.user,
        organization_id=employee.organization_id,
        title="Leave Request Submitted",
        message=(
            f"{employee_name} (Employee ID: {employee_identifier}) "
            f"has requested {leave_label} from "
            f"{start_date_label} to {end_date_label} "
            f"({leave_request.working_days_count} working days). "
            f"Request ID: {leave_request.pk}. Please review."
        ),
        category="LEAVE",
        metadata={
            "event": "leave_request_submitted",
            "leave_request_id": leave_request.pk,
            "employee_identifier": employee_identifier,
            "employee_name": employee_name,
            "status": leave_request.status,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
        },
    )

    return leave_request


@transaction.atomic
def decide_leave_request(
    leave_request_id,
    reviewer,
    decision,
    remarks="",
):
    leave_request = (
        LeaveRequest.objects.select_for_update()
        .select_related("employee", "manager_at_request")
        .get(pk=leave_request_id)
    )

    # Authorization must be checked before the workflow state.
    if leave_request.manager_at_request_id != reviewer.pk:
        raise PermissionError(
            "Only the employee's assigned manager can review this request."
        )

    _validate_manager_eligibility(
        reviewer,
        leave_request.organization_id,
    )

    if leave_request.status != LeaveRequest.Status.PENDING:
        raise ValueError(
            "Only pending leave requests can be reviewed."
        )

    if decision not in (
        LeaveRequest.Status.APPROVED,
        LeaveRequest.Status.REJECTED,
    ):
        raise ValueError("Unsupported leave decision.")

    leave_request.status = decision
    leave_request.reviewed_by = reviewer
    leave_request.reviewed_at = timezone.now()
    leave_request.review_remarks = (remarks or "").strip()

    leave_request.save(
        update_fields=[
            "status",
            "reviewed_by",
            "reviewed_at",
            "review_remarks",
            "updated_at",
        ]
    )
    decision_word = (
        "approved"
        if decision == LeaveRequest.Status.APPROVED
        else "rejected"
    )
    leave_type_name = leave_request.leave_type.name.strip()

    leave_label = (
        leave_type_name
        if leave_type_name.casefold().endswith("leave")
        else f"{leave_type_name} leave"
    )

    start_date_label = leave_request.start_date.strftime("%d %b %Y")
    end_date_label = leave_request.end_date.strftime("%d %b %Y")

    message = (
        f"Your {leave_label} request "
        f"(#{leave_request.pk}) from {start_date_label} to "
        f"{end_date_label} has been {decision_word}."
    )

    if leave_request.review_remarks:
        message += (
            "\nManager's remarks: "
            f"{leave_request.review_remarks}"
        )

    schedule_notification(
        user=leave_request.employee.user,
        organization_id=leave_request.organization_id,
        title=f"Leave Request {decision_word.title()}",
        message=message,
        category="LEAVE",
        metadata={
            "event": "leave_request_decided",
            "leave_request_id": leave_request.pk,
            "status": leave_request.status,
            "start_date": leave_request.start_date.isoformat(),
            "end_date": leave_request.end_date.isoformat(),
        },
    )

    return leave_request


@transaction.atomic
def cancel_leave_request(leave_request_id, employee):
    leave_request = (
        LeaveRequest.objects.select_for_update()
        .get(pk=leave_request_id)
    )

    if leave_request.employee_id != employee.pk:
        raise PermissionError(
            "You are not authorized to cancel this leave request."
        )

    if leave_request.status != LeaveRequest.Status.PENDING:
        raise ValueError(
            "Only pending leave requests can be cancelled."
        )

    leave_request.status = LeaveRequest.Status.CANCELLED
    leave_request.save(
        update_fields=["status", "updated_at"]
    )

    manager_user = leave_request.manager_at_request.user

    if manager_user is not None:
        employee_name = " ".join(
            part
            for part in (
                leave_request.employee.first_name,
                leave_request.employee.last_name,
            )
            if part
        ).strip()

        onboarding_reference = (
            leave_request.employee.onboarding_reference
        )

        if onboarding_reference:
            employee_name = (
                f"{employee_name} ({onboarding_reference})"
            )

        schedule_notification(
            user=manager_user,
            organization_id=leave_request.organization_id,
            title="Leave request cancelled",
            message=(
                f"{employee_name or 'An employee'} cancelled their "
                f"{leave_request.leave_type.name} request for "
                f"{leave_request.start_date} to "
                f"{leave_request.end_date}."
            ),
            category="LEAVE",
            metadata={
                "event": "leave_request_cancelled",
                "leave_request_id": leave_request.pk,
                "status": LeaveRequest.Status.CANCELLED,
                "onboarding_reference": onboarding_reference,
            },
        )

    return leave_request



def get_employee_leave_balance_summary(employee, as_of_date=None):
    """
    Return leave balances for the employee that are active
    on the requested date.

    Approved leave requests count against the balance.
    Pending, rejected, and cancelled requests do not.
    """
    _require_active_employee(employee)

    if as_of_date is None:
        as_of_date = local_today(employee)

    balances = (
        LeaveBalance.objects.filter(
            organization_id=employee.organization_id,
            employee=employee,
            period_start__lte=as_of_date,
            period_end__gte=as_of_date,
        )
        .select_related("leave_type")
        .order_by("period_start", "leave_type__name")
    )

    summaries = []

    for balance in balances:
        approved_requests = LeaveRequest.objects.filter(
            organization_id=employee.organization_id,
            employee=employee,
            leave_type_id=balance.leave_type_id,
            status=LeaveRequest.Status.APPROVED,
            start_date__lte=balance.period_end,
            end_date__gte=balance.period_start,
        ).only(
            "start_date",
            "end_date",
            "working_days_count",
        )

        used_days = 0
        attendance_policy = None

        for leave_request in approved_requests:
            # Use the saved working-day count when the entire
            # request falls within this balance period.
            if (
                leave_request.start_date >= balance.period_start
                and leave_request.end_date <= balance.period_end
            ):
                used_days += leave_request.working_days_count
                continue

            # If a request crosses a balance-period boundary,
            # count only the working dates inside this period.
            overlap_start = max(
                leave_request.start_date,
                balance.period_start,
            )
            overlap_end = min(
                leave_request.end_date,
                balance.period_end,
            )

            if attendance_policy is None:
                attendance_policy = get_attendance_policy(employee)

            overlap_working_dates = _working_dates(
                employee,
                attendance_policy,
                overlap_start,
                overlap_end,
            )

            used_days += len(overlap_working_dates)

        summaries.append(
            {
                "balance_id": balance.pk,
                "leave_type_id": balance.leave_type_id,
                "leave_type_code": balance.leave_type.code,
                "leave_type_name": balance.leave_type.name,
                "period_start": balance.period_start,
                "period_end": balance.period_end,
                "entitled_days": balance.entitled_days,
                "used_days": used_days,
                "remaining_days": balance.entitled_days - used_days,
            }
        )

    return summaries