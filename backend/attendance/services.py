import logging
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.db import transaction
from django.utils import timezone

from employees.models import Employee

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

logger = logging.getLogger(__name__)


def get_employee_for_user(user):
    try:
        return user.employee_record
    except (Employee.DoesNotExist, AttributeError):
        raise PermissionError(
            "Authenticated user is not linked to an employee record."
        )


def get_attendance_policy(employee):
    if employee.organization_id is None:
        raise ValueError("Employee is not assigned to an organization.")

    policy, _ = AttendancePolicy.objects.get_or_create(
        organization_id=employee.organization_id
    )
    return policy


def _zone_for_policy(policy):
    try:
        return ZoneInfo(policy.timezone_name)
    except (ZoneInfoNotFoundError, ValueError):
        raise ValueError(
            f"Invalid organization timezone: {policy.timezone_name}"
        )


def _local_now(policy, reference=None):
    zone = _zone_for_policy(policy)
    value = reference or timezone.now()

    if timezone.is_naive(value):
        value = timezone.make_aware(value, zone)

    return value.astimezone(zone)


def local_today(employee):
    return _local_now(get_attendance_policy(employee)).date()


def _policy_snapshot(policy):
    return {
        "timezone_name": policy.timezone_name,
        "work_start_time": policy.work_start_time.isoformat(),
        "work_end_time": policy.work_end_time.isoformat(),
        "working_days": list(policy.working_days),
        "grace_minutes": policy.grace_minutes,
        "consecutive_late_absence_threshold": (
            policy.consecutive_late_absence_threshold
        ),
        "consecutive_late_absence_enabled": (
            policy.consecutive_late_absence_enabled
        ),
        "allow_same_day_wfh": policy.allow_same_day_wfh,
        "same_day_wfh_start_time": (
            policy.same_day_wfh_start_time.isoformat()
        ),
        "same_day_wfh_cutoff_time": (
            policy.same_day_wfh_cutoff_time.isoformat()
        ),
        "allow_planned_wfh": policy.allow_planned_wfh,
        "forgot_to_apply_wfh_reminder_enabled": (
            policy.forgot_to_apply_wfh_reminder_enabled
        ),
        "forgot_to_apply_wfh_reminder_before_cutoff_hours": (
            policy.forgot_to_apply_wfh_reminder_before_cutoff_hours
        ),
        "auto_mark_absent_after_wfh_cutoff": (
            policy.auto_mark_absent_after_wfh_cutoff
        ),
        "incomplete_checkout_enabled": (
            policy.incomplete_checkout_enabled
        ),
        "incomplete_checkout_grace_minutes": (
            policy.incomplete_checkout_grace_minutes
        ),
    }


def _write_audit(
    employee,
    performed_by,
    event_type,
    entity_type,
    entity_id,
    before_data=None,
    after_data=None,
    details=None,
):
    policy = get_attendance_policy(employee)

    if not policy.audit_logging_enabled:
        return None

    before_data = before_data or {}
    after_data = after_data or {}
    details = details or {}

    if policy.audit_detail_level == AttendancePolicy.AuditDetailLevel.SUMMARY:
        before_data = (
            {"status": before_data["status"]}
            if "status" in before_data
            else {}
        )
        after_data = (
            {"status": after_data["status"]}
            if "status" in after_data
            else {}
        )
        details = {}

    return AttendanceAuditLog.objects.create(
        organization_id=employee.organization_id,
        employee=employee,
        performed_by=performed_by,
        event_type=event_type,
        entity_type=entity_type,
        entity_id=entity_id,
        before_data=before_data,
        after_data=after_data,
        details=details,
    )


def _schedule_notification(
    user,
    organization,
    policy,
    title,
    message,
    category,
    metadata=None,
):
    if user is None or not policy.notifications_enabled:
        return

    send_in_app = policy.in_app_notifications_enabled
    send_email = policy.email_notifications_enabled

    if not send_in_app and not send_email:
        return

    def dispatch():
        try:
            from notifications.attendance_dispatch import (
                dispatch_attendance_notification,
            )

            dispatch_attendance_notification(
                user=user,
                organization=organization,
                title=title,
                message=message,
                category=category,
                metadata=metadata or {},
                send_in_app=send_in_app,
                send_email=send_email,
            )
        except Exception:
            # Notification failure must not roll back a completed attendance
            # or approval transaction.
            logger.exception(
                "Attendance notification dispatch failed for user id=%s",
                user.pk,
            )

    transaction.on_commit(dispatch)


def _is_working_day(employee, policy, day):
    if day.weekday() not in policy.working_days:
        return False

    return not Holiday.objects.filter(
        organization_id=employee.organization_id,
        date=day,
        is_active=True,
    ).exists()


def _working_dates(employee, policy, start_date, end_date):
    result = []
    current = start_date

    while current <= end_date:
        if _is_working_day(employee, policy, current):
            result.append(current)
        current += timedelta(days=1)

    return result


def _approved_wfh_for_date(employee, attendance_date):
    return (
        WFHRequest.objects.filter(
            employee=employee,
            status=WFHRequest.Status.APPROVED,
            start_date__lte=attendance_date,
            end_date__gte=attendance_date,
        )
        .order_by("-id")
        .first()
    )


def _previous_consecutive_late_count(employee, policy, attendance_date):
    current = attendance_date - timedelta(days=1)
    count = 0

    for _ in range(90):
        if _is_working_day(employee, policy, current):
            record = AttendanceRecord.objects.filter(
                employee=employee,
                attendance_date=current,
            ).first()

            was_late = bool(
                record is not None
                and (
                    record.policy_snapshot.get("arrival_was_late", False)
                    or record.status == AttendanceRecord.Status.LATE
                )
            )

            if not was_late:
                break

            count += 1

        current -= timedelta(days=1)

    return count


def _require_active_employee(employee):
    if employee.status != Employee.Status.ACTIVE:
        raise ValueError(
            "Only active employees can use Attendance and WFH."
        )

    if employee.user_id is None or not employee.user.is_active:
        raise ValueError("Employee login account must be active.")


@transaction.atomic
def check_in_employee(employee):
    _require_active_employee(employee)

    policy = get_attendance_policy(employee)
    now = _local_now(policy)
    day = now.date()

    if not _is_working_day(employee, policy, day):
        raise ValueError(
            "Today is not a configured working day for this organization."
        )

    existing = (
        AttendanceRecord.objects.select_for_update()
        .filter(employee=employee, attendance_date=day)
        .first()
    )
    approved_wfh = _approved_wfh_for_date(employee, day)

    if existing is not None:
        if (
            existing.status == AttendanceRecord.Status.WFH
            and existing.source == AttendanceRecord.Source.WFH
            and existing.check_in_at is None
            and approved_wfh is not None
            and existing.source_reference == f"WFH:{approved_wfh.pk}"
        ):
            existing.check_in_at = now
            existing.save(update_fields=["check_in_at", "updated_at"])

            _write_audit(
                employee,
                employee.user,
                AttendanceAuditLog.EventType.CHECK_IN,
                "AttendanceRecord",
                existing.pk,
                before_data={
                    "status": existing.status,
                    "check_in_at": None,
                },
                after_data={
                    "status": existing.status,
                    "check_in_at": now.isoformat(),
                },
                details={"source": existing.source},
            )
            return existing

        raise ValueError("Attendance has already been marked for today.")

    if approved_wfh is not None:
        record = AttendanceRecord.objects.create(
            employee=employee,
            attendance_date=day,
            check_in_at=now,
            status=AttendanceRecord.Status.WFH,
            source=AttendanceRecord.Source.WFH,
            source_reference=f"WFH:{approved_wfh.pk}",
            policy_snapshot=_policy_snapshot(policy),
            remarks=f"Approved WFH request #{approved_wfh.pk}.",
        )
    else:
        zone = _zone_for_policy(policy)
        grace_deadline = datetime.combine(
            day,
            policy.work_start_time,
            tzinfo=zone,
        ) + timedelta(minutes=policy.grace_minutes)

        prior_late_count = 0
        arrival_was_late = now > grace_deadline

        if not arrival_was_late:
            attendance_status = AttendanceRecord.Status.PRESENT
            remarks = ""
        else:
            attendance_status = AttendanceRecord.Status.LATE
            remarks = "Check-in occurred after the configured grace period."

            if policy.consecutive_late_absence_enabled:
                prior_late_count = _previous_consecutive_late_count(
                    employee,
                    policy,
                    day,
                )

                if (
                    prior_late_count + 1
                    >= policy.consecutive_late_absence_threshold
                ):
                    attendance_status = AttendanceRecord.Status.ABSENT
                    remarks = (
                        "Configured consecutive-late threshold was reached."
                    )

        snapshot = _policy_snapshot(policy)
        snapshot["arrival_was_late"] = arrival_was_late
        snapshot["consecutive_late_count"] = (
            prior_late_count + 1 if arrival_was_late else 0
        )

        record = AttendanceRecord.objects.create(
            employee=employee,
            attendance_date=day,
            check_in_at=now,
            status=attendance_status,
            source=AttendanceRecord.Source.WORKSPHERE,
            policy_snapshot=snapshot,
            remarks=remarks,
        )

    _write_audit(
        employee,
        employee.user,
        AttendanceAuditLog.EventType.CHECK_IN,
        "AttendanceRecord",
        record.pk,
        after_data={
            "status": record.status,
            "check_in_at": record.check_in_at.isoformat(),
        },
        details={"source": record.source},
    )

    _schedule_notification(
        employee.user,
        employee.organization,
        policy,
        "Attendance check-in recorded",
        (
            f"Your attendance for {day.isoformat()} "
            f"was recorded as {record.status}."
        ),
        "ATTENDANCE",
        {"attendance_record_id": record.pk},
    )

    return record


@transaction.atomic
def check_out_employee(employee):
    _require_active_employee(employee)

    policy = get_attendance_policy(employee)
    now = _local_now(policy)

    record = (
        AttendanceRecord.objects.select_for_update()
        .filter(employee=employee, attendance_date=now.date())
        .first()
    )

    if record is None or record.check_in_at is None:
        raise ValueError("Check-in must be completed before check-out.")

    if record.check_out_at is not None:
        raise ValueError("Attendance has already been checked out.")

    open_exception = AttendanceException.objects.filter(
        attendance_record=record,
        status=AttendanceException.Status.OPEN,
    ).first()

    if open_exception is not None:
        raise ValueError("Attendance is awaiting manager review.")

    if record.status == AttendanceRecord.Status.INCOMPLETE:
        if policy.incomplete_checkout_requires_manager_review:
            raise ValueError(
                "Manager review has finalized this incomplete checkout."
            )

        record.status = record.policy_snapshot.get(
            "status_before_incomplete",
            AttendanceRecord.Status.PRESENT,
        )

    before = {
        "status": record.status,
        "check_out_at": None,
    }

    record.check_out_at = now
    record.save(
        update_fields=["check_out_at", "status", "updated_at"]
    )

    _write_audit(
        employee,
        employee.user,
        AttendanceAuditLog.EventType.CHECK_OUT,
        "AttendanceRecord",
        record.pk,
        before_data=before,
        after_data={
            "status": record.status,
            "check_out_at": record.check_out_at.isoformat(),
        },
    )

    _schedule_notification(
        employee.user,
        employee.organization,
        policy,
        "Attendance check-out recorded",
        f"Your check-out for {record.attendance_date.isoformat()} was recorded.",
        "ATTENDANCE",
        {"attendance_record_id": record.pk},
    )

    return record


def get_my_attendance(employee, start_date=None, end_date=None):
    records = AttendanceRecord.objects.filter(employee=employee)

    if start_date is not None:
        records = records.filter(attendance_date__gte=start_date)

    if end_date is not None:
        records = records.filter(attendance_date__lte=end_date)

    return records.order_by("-attendance_date")


def _validate_manager_eligibility(manager, organization_id):
    """
    Validate that an employee is eligible to act as a manager.

    This function does not assign or modify a manager.
    """
    from accounts.models import DocumentRequirement
    from employees.models import Employee, EmployeeDocument

    if manager is None:
        raise PermissionError("No manager has been assigned.")

    if manager.status != Employee.Status.ACTIVE:
        raise PermissionError(
            "The assigned manager must have an active employee status."
        )

    if manager.organization_id != organization_id:
        raise PermissionError(
            "The assigned manager must belong to the same organization."
        )

    if not (manager.employee_id or "").strip():
        raise PermissionError(
            "The assigned manager must have a permanent Employee ID."
        )

    if manager.user_id is None or not manager.user.is_active:
        raise PermissionError(
            "The assigned manager must have an active linked account."
        )

    required_requirements = list(
        DocumentRequirement.objects.filter(
            organization_id=organization_id,
            is_required=True,
            is_active=True,
        ).order_by("id")
    )

    if not required_requirements:
        raise PermissionError(
            "Manager eligibility cannot be verified because the "
            "organization has no active required document rules."
        )

    documents = {
        document.document_requirement_id: document
        for document in EmployeeDocument.objects.filter(
            employee=manager,
            document_requirement__organization_id=organization_id,
        )
    }

    outstanding = [
        requirement.code
        for requirement in required_requirements
        if (
            requirement.id not in documents
            or documents[requirement.id].status
            != EmployeeDocument.Status.VERIFIED
        )
    ]

    if outstanding:
        raise PermissionError(
            "The assigned manager has missing or unverified required "
            "documents: " + ", ".join(outstanding)
        )

    return manager


def _validate_manager_assignment(employee):
    """
    Resolve and validate the manager assigned to an employee.
    """
    manager = employee.manager

    if manager is None:
        raise ValueError(
            "A manager must be assigned before submitting a request."
        )

    try:
        return _validate_manager_eligibility(
            manager,
            employee.organization_id,
        )
    except PermissionError as exc:
        raise ValueError(
            f"Assigned manager is not eligible: {exc}"
        ) from exc


@transaction.atomic
def create_wfh_request(
    employee,
    request_type,
    start_date,
    end_date,
    reason,
):
    _require_active_employee(employee)

    if end_date < start_date:
        raise ValueError("WFH end date cannot be earlier than the start date.")

    if not reason or not reason.strip():
        raise ValueError("A reason is required for WFH.")

    policy = get_attendance_policy(employee)
    now = _local_now(policy)
    today = now.date()
    manager = _validate_manager_assignment(employee)

    if request_type == WFHRequest.RequestType.SAME_DAY:
        if not policy.allow_same_day_wfh:
            raise ValueError(
                "Same-day WFH is disabled by organization policy."
            )

        if start_date != today or end_date != today:
            raise ValueError("Same-day WFH must be requested for today only.")

        if not _is_working_day(employee, policy, today):
            raise ValueError("Same-day WFH is unavailable on a non-working day.")

        current_time = now.replace(tzinfo=None).time()

        if not (
            policy.same_day_wfh_start_time
            <= current_time
            <= policy.same_day_wfh_cutoff_time
        ):
            raise ValueError(
                "Same-day WFH can only be requested during the configured window."
            )

        if AttendanceRecord.objects.filter(
            employee=employee,
            attendance_date=today,
        ).exists():
            raise ValueError(
                "Attendance already exists for today; a same-day WFH "
                "request cannot override it."
            )

    elif request_type == WFHRequest.RequestType.PLANNED:
        if not policy.allow_planned_wfh:
            raise ValueError(
                "Planned WFH is disabled by organization policy."
            )

        if start_date <= today:
            raise ValueError("Planned WFH must start on a future date.")

    else:
        raise ValueError("Unsupported WFH request type.")

    workdays = _working_dates(employee, policy, start_date, end_date)

    if not workdays:
        raise ValueError(
            "The requested period contains no configured working days."
        )

    overlap = WFHRequest.objects.select_for_update().filter(
        employee=employee,
        status__in=[
            WFHRequest.Status.PENDING,
            WFHRequest.Status.APPROVED,
        ],
        start_date__lte=end_date,
        end_date__gte=start_date,
    ).exists()

    if overlap:
        raise ValueError(
            "An active WFH request already overlaps the selected dates."
        )

    request_obj = WFHRequest.objects.create(
        employee=employee,
        manager_at_request=manager,
        request_type=request_type,
        start_date=start_date,
        end_date=end_date,
        reason=reason.strip(),
        status=WFHRequest.Status.PENDING,
    )

    _write_audit(
        employee,
        employee.user,
        AttendanceAuditLog.EventType.WFH_REQUEST_CREATED,
        "WFHRequest",
        request_obj.pk,
        after_data={
            "status": request_obj.status,
            "request_type": request_obj.request_type,
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
        },
    )

    if policy.notify_on_wfh_request:
        employee_identifier = (
            employee.employee_id
            or employee.onboarding_reference
            or f"Employee #{employee.pk}"
        )

        employee_name = (
            f"{employee.first_name} {employee.last_name}".strip()
        )

        request_type_label = (
            "planned work from home"
            if request_obj.request_type == WFHRequest.RequestType.PLANNED
            else "same-day work from home"
        )

        start_date_label = start_date.strftime("%d %b %Y")
        end_date_label = end_date.strftime("%d %b %Y")

        duration_label = (
            f"{len(workdays)} working day"
            if len(workdays) == 1
            else f"{len(workdays)} working days"
        )

        _schedule_notification(
            manager.user,
            employee.organization,
            policy,
            "WFH Request Needs Review",
            (
                f"WFH request #{request_obj.pk}: "
                f"{employee_name} (Employee ID: {employee_identifier}) "
                f"has requested {request_type_label} from "
                f"{start_date_label} to {end_date_label} "
                f"({duration_label}). "
                "Please review the request."
            ),
            "WFH",
            {"wfh_request_id": request_obj.pk},
        )

    return request_obj


def _is_assigned_manager(wfh_request, reviewer):
    try:
        manager_employee = reviewer.employee_record
    except (Employee.DoesNotExist, AttributeError):
        return False

    return bool(
        reviewer.is_active
        and wfh_request.manager_at_request_id == manager_employee.pk
        and manager_employee.status == Employee.Status.ACTIVE
        and manager_employee.organization_id
        == wfh_request.employee.organization_id
    )


def _create_wfh_attendance_records(wfh_request):
    employee = wfh_request.employee
    policy = get_attendance_policy(employee)

    days = _working_dates(
        employee,
        policy,
        wfh_request.start_date,
        wfh_request.end_date,
    )

    # Validate all requested dates before creating any daily records.
    for day in days:
        existing = AttendanceRecord.objects.select_for_update().filter(
            employee=employee,
            attendance_date=day,
        ).first()

        if existing is not None:
            if (
                existing.status == AttendanceRecord.Status.WFH
                and existing.source == AttendanceRecord.Source.WFH
                and existing.source_reference == f"WFH:{wfh_request.pk}"
            ):
                continue

            raise ValueError(
                f"Cannot approve WFH for {day.isoformat()}: "
                "an attendance record already exists."
            )

    for day in days:
        AttendanceRecord.objects.get_or_create(
            employee=employee,
            attendance_date=day,
            defaults={
                "status": AttendanceRecord.Status.WFH,
                "source": AttendanceRecord.Source.WFH,
                "source_reference": f"WFH:{wfh_request.pk}",
                "policy_snapshot": _policy_snapshot(policy),
                "remarks": f"Created from approved WFH request #{wfh_request.pk}.",
            },
        )


@transaction.atomic
def approve_wfh_request(wfh_request, reviewer):
    # First, confirm that this reviewer is the assigned manager.
    if not _is_assigned_manager(wfh_request, reviewer):
        raise PermissionError(
            "Only the employee's assigned manager can approve this WFH request."
        )

    # Then confirm that the assigned manager is still eligible.
    _validate_manager_eligibility(
        wfh_request.manager_at_request,
        wfh_request.employee.organization_id,
    )

    # Only pending requests can be approved.
    if wfh_request.status != WFHRequest.Status.PENDING:
        raise ValueError("Only pending WFH requests can be approved.")

    wfh_request.status = WFHRequest.Status.APPROVED
    wfh_request.reviewed_by = reviewer
    wfh_request.reviewed_at = timezone.now()
    wfh_request.review_remarks = ""

    wfh_request.save(
        update_fields=[
            "status",
            "reviewed_by",
            "reviewed_at",
            "review_remarks",
            "updated_at",
        ]
    )

    # If attendance conflicts, the atomic transaction rolls approval back.
    _create_wfh_attendance_records(wfh_request)

    employee = wfh_request.employee
    policy = get_attendance_policy(employee)

    _write_audit(
        employee,
        reviewer,
        AttendanceAuditLog.EventType.WFH_REQUEST_APPROVED,
        "WFHRequest",
        wfh_request.pk,
        before_data={"status": WFHRequest.Status.PENDING},
        after_data={"status": wfh_request.status},
    )

    if policy.notify_on_wfh_decision:
        _schedule_notification(
            employee.user,
            employee.organization,
            policy,
            "WFH request approved",
            (
                f"Your WFH request for {wfh_request.start_date.isoformat()} "
                f"to {wfh_request.end_date.isoformat()} was approved."
            ),
            "WFH",
            {"wfh_request_id": wfh_request.pk},
        )

    return wfh_request


@transaction.atomic
def reject_wfh_request(wfh_request, reviewer, remarks=""):
    # First, confirm that this reviewer is the assigned manager.
    if not _is_assigned_manager(wfh_request, reviewer):
        raise PermissionError(
            "Only the employee's assigned manager can reject this WFH request."
        )

    # Then confirm that the assigned manager is still eligible.
    _validate_manager_eligibility(
        wfh_request.manager_at_request,
        wfh_request.employee.organization_id,
    )

    # Only pending requests can be rejected.
    if wfh_request.status != WFHRequest.Status.PENDING:
        raise ValueError("Only pending WFH requests can be rejected.")

    wfh_request.status = WFHRequest.Status.REJECTED
    wfh_request.reviewed_by = reviewer
    wfh_request.reviewed_at = timezone.now()
    wfh_request.review_remarks = (remarks or "").strip()

    wfh_request.save(
        update_fields=[
            "status",
            "reviewed_by",
            "reviewed_at",
            "review_remarks",
            "updated_at",
        ]
    )

    employee = wfh_request.employee
    policy = get_attendance_policy(employee)

    _write_audit(
        employee,
        reviewer,
        AttendanceAuditLog.EventType.WFH_REQUEST_REJECTED,
        "WFHRequest",
        wfh_request.pk,
        before_data={"status": WFHRequest.Status.PENDING},
        after_data={"status": wfh_request.status},
        details={"review_remarks": wfh_request.review_remarks},
    )

    if policy.notify_on_wfh_decision:
        _schedule_notification(
            employee.user,
            employee.organization,
            policy,
            "WFH request rejected",
            (
                f"Your WFH request for {wfh_request.start_date.isoformat()} "
                f"to {wfh_request.end_date.isoformat()} was rejected. "
                f"Reason: {wfh_request.review_remarks or 'Not provided'}"
            ),
            "WFH",
            {"wfh_request_id": wfh_request.pk},
        )

    return wfh_request


def _manager_can_review_exception(exception_obj, reviewer):
    try:
        manager_employee = reviewer.employee_record
    except (Employee.DoesNotExist, AttributeError):
        return False

    return bool(
        reviewer.is_active
        and exception_obj.assigned_manager_id == manager_employee.pk
        and manager_employee.status == Employee.Status.ACTIVE
        and manager_employee.organization_id == exception_obj.organization_id
    )


@transaction.atomic
def resolve_attendance_exception(
    exception_obj,
    reviewer,
    resolution,
    check_out_at=None,
    review_notes="",
):
    if not _manager_can_review_exception(exception_obj, reviewer):
        raise PermissionError(
            "Only the assigned manager can resolve this attendance exception."
        )

    if exception_obj.status != AttendanceException.Status.OPEN:
        raise ValueError("This attendance exception is already resolved.")

    record = exception_obj.attendance_record

    if record is None:
        raise ValueError("The original attendance record is no longer available.")

    employee = exception_obj.employee
    policy = get_attendance_policy(employee)

    if resolution == AttendanceException.Resolution.CONFIRMED_INCOMPLETE:
        previous = record.policy_snapshot.get(
            "status_before_incomplete",
            record.status,
        )
        record.policy_snapshot = dict(record.policy_snapshot or {})
        record.policy_snapshot["status_before_incomplete"] = previous
        record.status = AttendanceRecord.Status.INCOMPLETE
        record.save(update_fields=["status", "policy_snapshot", "updated_at"])

    elif resolution == AttendanceException.Resolution.CORRECTED_CHECKOUT:
        if check_out_at is None:
            raise ValueError("A corrected checkout timestamp is required.")

        if timezone.is_naive(check_out_at):
            check_out_at = timezone.make_aware(
                check_out_at,
                _zone_for_policy(policy),
            )

        check_out_at = check_out_at.astimezone(_zone_for_policy(policy))

        if record.check_in_at is None:
            raise ValueError("The attendance record has no check-in.")

        if check_out_at < record.check_in_at:
            raise ValueError("Checkout cannot occur before check-in.")

        if check_out_at > _local_now(policy):
            raise ValueError("Checkout cannot be in the future.")

        if check_out_at.date() != record.attendance_date:
            raise ValueError(
                "Corrected checkout must be on the attendance date."
            )

        previous = record.policy_snapshot.get(
            "status_before_incomplete",
            AttendanceRecord.Status.PRESENT,
        )
        record.status = previous
        record.check_out_at = check_out_at
        record.save(
            update_fields=["status", "check_out_at", "updated_at"]
        )

    else:
        raise ValueError("Unsupported attendance exception resolution.")

    exception_obj.status = AttendanceException.Status.RESOLVED
    exception_obj.resolution = resolution
    exception_obj.reviewed_by = reviewer
    exception_obj.reviewed_at = timezone.now()
    exception_obj.review_notes = (review_notes or "").strip()

    exception_obj.save(
        update_fields=[
            "status",
            "resolution",
            "reviewed_by",
            "reviewed_at",
            "review_notes",
            "updated_at",
        ]
    )

    _write_audit(
        employee,
        reviewer,
        AttendanceAuditLog.EventType.ATTENDANCE_EXCEPTION_RESOLVED,
        "AttendanceException",
        exception_obj.pk,
        after_data={
            "status": exception_obj.status,
            "resolution": exception_obj.resolution,
        },
        details={"review_notes": exception_obj.review_notes},
    )

    _schedule_notification(
        employee.user,
        employee.organization,
        policy,
        "Attendance exception reviewed",
        (
            f"Your incomplete-checkout exception for "
            f"{record.attendance_date.isoformat()} has been reviewed."
        ),
        "ATTENDANCE",
        {"attendance_exception_id": exception_obj.pk},
    )

    return exception_obj


@transaction.atomic
def process_incomplete_checkouts(reference_now=None):
    flagged = 0

    policies = AttendancePolicy.objects.select_related("organization")

    for policy in policies.iterator():
        if not policy.incomplete_checkout_enabled:
            continue

        now = _local_now(policy, reference_now)
        zone = _zone_for_policy(policy)

        records = AttendanceRecord.objects.filter(
            employee__organization_id=policy.organization_id,
            attendance_date__lte=now.date(),
            check_in_at__isnull=False,
            check_out_at__isnull=True,
        ).exclude(
            status=AttendanceRecord.Status.INCOMPLETE
        ).select_related(
            "employee",
            "employee__organization",
            "employee__user",
            "employee__manager",
            "employee__manager__user",
        )

        for record in records.iterator():
            employee = record.employee

            if not _is_working_day(employee, policy, record.attendance_date):
                continue

            deadline = datetime.combine(
                record.attendance_date,
                policy.work_end_time,
                tzinfo=zone,
            ) + timedelta(
                minutes=policy.incomplete_checkout_grace_minutes
            )

            if now < deadline:
                continue

            if AttendanceException.objects.filter(
                attendance_record=record,
                status=AttendanceException.Status.OPEN,
            ).exists():
                continue

            already_resolved = AttendanceException.objects.filter(
                attendance_record=record,
                status=AttendanceException.Status.RESOLVED,
            ).exists()

            if already_resolved:
                continue

            old_status = record.status
            snapshot = dict(record.policy_snapshot or {})
            snapshot.setdefault("status_before_incomplete", old_status)
            record.policy_snapshot = snapshot

            if policy.incomplete_checkout_auto_mark_incomplete:
                record.status = AttendanceRecord.Status.INCOMPLETE
                record.save(
                    update_fields=[
                        "status",
                        "policy_snapshot",
                        "updated_at",
                    ]
                )
            else:
                record.save(
                    update_fields=["policy_snapshot", "updated_at"]
                )

            exception_obj = None

            if policy.incomplete_checkout_requires_manager_review:
                exception_obj = AttendanceException.objects.create(
                    attendance_record=record,
                    original_record_id=record.pk,
                    organization_id=employee.organization_id,
                    employee=employee,
                    assigned_manager_id=employee.manager_id,
                    status=AttendanceException.Status.OPEN,
                )

            _write_audit(
                employee,
                None,
                AttendanceAuditLog.EventType.INCOMPLETE_CHECKOUT_FLAGGED,
                "AttendanceRecord",
                record.pk,
                before_data={"status": old_status},
                after_data={"status": record.status},
                details={
                    "manager_review_required": (
                        policy.incomplete_checkout_requires_manager_review
                    )
                },
            )

            if policy.incomplete_checkout_reminder_enabled:
                _schedule_notification(
                    employee.user,
                    employee.organization,
                    policy,
                    "Incomplete checkout needs attention",
                    (
                        f"Your attendance for "
                        f"{record.attendance_date.isoformat()} "
                        "has an incomplete checkout."
                    ),
                    "ATTENDANCE",
                    {"attendance_record_id": record.pk},
                )

            manager = employee.manager

            if (
                exception_obj is not None
                and manager is not None
                and manager.user_id
            ):
                _schedule_notification(
                    manager.user,
                    employee.organization,
                    policy,
                    "Incomplete checkout needs review",
                    (
                        f"Attendance for {employee} on "
                        f"{record.attendance_date.isoformat()} "
                        "requires your review."
                    ),
                    "ATTENDANCE",
                    {
                        "attendance_exception_id": exception_obj.pk,
                        "attendance_record_id": record.pk,
                    },
                )

            flagged += 1

    return flagged


def send_forgot_to_apply_wfh_reminders(reference_now=None):
    from leave_management.models import LeaveRequest

    sent = 0

    policies = AttendancePolicy.objects.select_related("organization")

    for policy in policies.iterator():
        if (
            not policy.forgot_to_apply_wfh_reminder_enabled
            or not policy.allow_same_day_wfh
        ):
            continue

        now = _local_now(policy, reference_now)
        target_date = now.date()
        zone = _zone_for_policy(policy)

        employees = Employee.objects.filter(
            organization_id=policy.organization_id,
            status=Employee.Status.ACTIVE,
            user__is_active=True,
        ).select_related(
            "organization",
            "user",
            "manager",
        )

        deadline = datetime.combine(
            target_date,
            policy.same_day_wfh_cutoff_time,
            tzinfo=zone,
        )

        reminder_at = deadline - timedelta(
            hours=policy.forgot_to_apply_wfh_reminder_before_cutoff_hours
        )

        window_start = datetime.combine(
            target_date,
            policy.same_day_wfh_start_time,
            tzinfo=zone,
        )

        # Defensive check for policies not validated through a model form.
        if reminder_at < window_start:
            logger.error(
                "WFH reminder time falls before the application window "
                "for organization id=%s.",
                policy.organization_id,
            )
            continue

        # Do not send reminders before their configured time or after expiry.
        if now < reminder_at or now >= deadline:
            continue

        for employee in employees.iterator():
            if not _is_working_day(employee, policy, target_date):
                continue

            # Existing attendance means no forgotten-WFH reminder is needed.
            if AttendanceRecord.objects.filter(
                employee=employee,
                attendance_date=target_date,
            ).exists():
                continue

            # Approved leave means absence should not be inferred.
            if LeaveRequest.objects.filter(
                organization_id=employee.organization_id,
                employee=employee,
                status=LeaveRequest.Status.APPROVED,
                start_date__lte=target_date,
                end_date__gte=target_date,
            ).exists():
                continue

            # An existing pending or approved WFH request means the employee
            # has already applied, so the forgotten-application reminder
            # should not be sent.
            if WFHRequest.objects.filter(
                employee=employee,
                status__in=[
                    WFHRequest.Status.PENDING,
                    WFHRequest.Status.APPROVED,
                ],
                start_date__lte=target_date,
                end_date__gte=target_date,
            ).exists():
                continue

            reminder, created = AttendanceReminderLog.objects.get_or_create(
                employee=employee,
                reminder_type=(
                    AttendanceReminderLog.ReminderType.WFH_APPLICATION
                ),
                reminder_date=target_date,
                defaults={
                    "organization_id": employee.organization_id,
                },
            )

            # The database uniqueness constraint prevents duplicate reminders.
            if not created:
                continue

            _write_audit(
                employee,
                None,
                AttendanceAuditLog.EventType.WFH_REMINDER_SENT,
                "AttendanceReminderLog",
                reminder.pk,
                details={
                    "reminder_id": reminder.pk,
                    "reminder_date": target_date.isoformat(),
                    "deadline": deadline.isoformat(),
                    "timezone_name": policy.timezone_name,
                },
            )

            deadline_label = deadline.strftime("%I:%M %p").lstrip("0")
            date_label = target_date.strftime("%d %b %Y")

            _schedule_notification(
                employee.user,
                employee.organization,
                policy,
                "Reminder: WFH Application Deadline Approaching",
                (
                    f"No attendance record, approved leave, or active "
                    f"WFH request was found for {date_label}. If you are "
                    f"working from home, submit your same-day WFH request "
                    f"by {deadline_label} ({policy.timezone_name}). "
                    "If you do not apply before the deadline, your "
                    "attendance may be marked ABSENT according to company "
                    "policy."
                ),
                "WFH_REMINDER",
                {
                    "reminder_date": target_date.isoformat(),
                    "deadline": deadline.isoformat(),
                    "timezone_name": policy.timezone_name,
                },
            )

            sent += 1

    return sent


def process_missing_attendance_absences(reference_now=None):
    from leave_management.models import LeaveRequest

    marked = 0

    policies = AttendancePolicy.objects.select_related("organization")

    for policy in policies.iterator():
        if (
            not policy.auto_mark_absent_after_wfh_cutoff
            or not policy.forgot_to_apply_wfh_reminder_enabled
            or not policy.allow_same_day_wfh
        ):
            continue

        now = _local_now(policy, reference_now)
        today = now.date()
        zone = _zone_for_policy(policy)

        # Check today and yesterday so a run shortly after midnight
        # can process the previous working day's expired deadline.
        candidate_dates = [
            today,
            today - timedelta(days=1),
        ]

        employees = Employee.objects.filter(
            organization_id=policy.organization_id,
            status=Employee.Status.ACTIVE,
            user__is_active=True,
        ).select_related(
            "organization",
            "user",
        )

        for employee in employees.iterator():
            for attendance_date in candidate_dates:
                if not _is_working_day(
                    employee,
                    policy,
                    attendance_date,
                ):
                    continue

                deadline = datetime.combine(
                    attendance_date,
                    policy.same_day_wfh_cutoff_time,
                    tzinfo=zone,
                )

                # Do not mark absence before the configured deadline.
                if now < deadline:
                    continue

                # A reminder must have been logged for this date first.
                reminder_exists = AttendanceReminderLog.objects.filter(
                    organization_id=employee.organization_id,
                    employee=employee,
                    reminder_type=(
                        AttendanceReminderLog.ReminderType.WFH_APPLICATION
                    ),
                    reminder_date=attendance_date,
                ).exists()

                if not reminder_exists:
                    continue

                # Never create an absence record when attendance already
                # exists for this employee and date.
                if AttendanceRecord.objects.filter(
                    employee=employee,
                    attendance_date=attendance_date,
                ).exists():
                    continue

                # Approved leave must prevent automatic absence.
                if LeaveRequest.objects.filter(
                    organization_id=employee.organization_id,
                    employee=employee,
                    status=LeaveRequest.Status.APPROVED,
                    start_date__lte=attendance_date,
                    end_date__gte=attendance_date,
                ).exists():
                    continue

                # Preserve pending requests and approved WFH requests.
                if WFHRequest.objects.filter(
                    employee=employee,
                    status__in=[
                        WFHRequest.Status.PENDING,
                        WFHRequest.Status.APPROVED,
                    ],
                    start_date__lte=attendance_date,
                    end_date__gte=attendance_date,
                ).exists():
                    continue

                record, created = AttendanceRecord.objects.get_or_create(
                    employee=employee,
                    attendance_date=attendance_date,
                    defaults={
                        "status": AttendanceRecord.Status.ABSENT,
                        "source": AttendanceRecord.Source.WORKSPHERE,
                        "policy_snapshot": _policy_snapshot(policy),
                        "remarks": (
                            "No attendance record, approved leave, or "
                            "active WFH request was recorded by the "
                            "configured deadline after a WFH reminder."
                        ),
                    },
                )

                if not created:
                    continue

                deadline_label = deadline.strftime("%I:%M %p").lstrip("0")
                date_label = attendance_date.strftime("%d %b %Y")

                _write_audit(
                    employee,
                    None,
                    AttendanceAuditLog.EventType.ABSENCE_MARKED,
                    "AttendanceRecord",
                    record.pk,
                    after_data={
                        "status": AttendanceRecord.Status.ABSENT,
                    },
                    details={
                        "attendance_date": attendance_date.isoformat(),
                        "deadline": deadline.isoformat(),
                        "timezone_name": policy.timezone_name,
                    },
                )

                _schedule_notification(
                    employee.user,
                    employee.organization,
                    policy,
                    "Attendance Marked Absent",
                    (
                        f"No attendance record, approved leave, or active "
                        f"WFH request was found for {date_label} by "
                        f"{deadline_label} ({policy.timezone_name}), "
                        "after a WFH application reminder. Your attendance "
                        "has been marked ABSENT according to company policy."
                    ),
                    "ATTENDANCE",
                    {
                        "attendance_date": attendance_date.isoformat(),
                        "reason": "MISSING_ATTENDANCE_AFTER_WFH_CUTOFF",
                    },
                )

                marked += 1

    return marked


def archive_old_attendance_records(reference_date=None):
    archived_count = 0

    policies = AttendancePolicy.objects.select_related("organization")

    for policy in policies.iterator():
        months = policy.archive_after_months

        if months is None:
            continue

        today = reference_date or _local_now(policy).date()
        month_index = today.year * 12 + today.month - 1 - months
        cutoff_date = date(
            month_index // 12,
            month_index % 12 + 1,
            1,
        )

        records = AttendanceRecord.objects.filter(
            employee__organization_id=policy.organization_id,
            attendance_date__lt=cutoff_date,
        ).select_related("employee", "employee__user")

        for record in records.iterator():
            if AttendanceException.objects.filter(
                attendance_record=record,
                status=AttendanceException.Status.OPEN,
            ).exists():
                continue

            employee = record.employee
            full_name = (
                f"{employee.first_name} {employee.last_name}".strip()
            )

            if not full_name and employee.user_id:
                full_name = employee.user.get_full_name()

            if not full_name:
                full_name = (
                    employee.onboarding_reference or str(employee.pk)
                )

            if (
                policy.archive_grouping
                == AttendancePolicy.ArchiveGrouping.MONTHLY
            ):
                period = record.attendance_date.strftime("%Y-%m")
            else:
                period = record.attendance_date.strftime("%Y")

            snapshot = {
                "attendance_date": record.attendance_date.isoformat(),
                "check_in_at": (
                    record.check_in_at.isoformat()
                    if record.check_in_at else None
                ),
                "check_out_at": (
                    record.check_out_at.isoformat()
                    if record.check_out_at else None
                ),
                "status": record.status,
                "source": record.source,
                "source_reference": record.source_reference,
                "remarks": record.remarks,
                "policy_snapshot": record.policy_snapshot,
            }

            with transaction.atomic():
                _, created = (
                    ArchivedAttendanceRecord.objects.get_or_create(
                        organization_id=employee.organization_id,
                        original_record_id=record.pk,
                        defaults={
                            "employee": employee,
                            "employee_id_snapshot": (
                                employee.employee_id
                                or employee.onboarding_reference
                                or str(employee.pk)
                            ),
                            "employee_name_snapshot": full_name,
                            "attendance_date": record.attendance_date,
                            "archive_period": period,
                            "record_snapshot": snapshot,
                        },
                    )
                )

                if created:
                    _write_audit(
                        employee,
                        None,
                        AttendanceAuditLog.EventType.ATTENDANCE_ARCHIVED,
                        "AttendanceRecord",
                        record.pk,
                        after_data={"archive_period": period},
                    )

                record.delete()
                archived_count += 1

    return archived_count