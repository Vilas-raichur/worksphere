from datetime import timedelta

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q

from .models import Employee, EmployeeEligibilityHistory


def _get_employee_eligibility_values(employee):
    """
    Return the employee fields that determine leave-policy eligibility.
    """
    return {
        "organization_id": employee.organization_id,
        "joining_date": employee.joining_date,
        "probation_end_date": employee.probation_end_date,
        "employee_type": employee.employee_type,
        "department_id": employee.department_id,
        "designation_id": employee.designation_id,
    }


@transaction.atomic
def create_initial_employee_eligibility(
    *,
    employee,
    effective_from,
    changed_by=None,
):
    """
    Create the first eligibility-history record for an employee.

    This is used during employee creation and in test fixtures.
    """
    locked_employee = Employee.objects.select_for_update(
        of=("self",)
    ).get(pk=employee.pk)

    if EmployeeEligibilityHistory.objects.filter(
        employee_id=locked_employee.pk
    ).exists():
        raise ValidationError(
            "Eligibility history already exists for this employee."
        )

    history = EmployeeEligibilityHistory(
        employee=locked_employee,
        effective_from=effective_from,
        effective_until=None,
        changed_by=changed_by,
        source=EmployeeEligibilityHistory.Source.EMPLOYEE_CREATION,
        **_get_employee_eligibility_values(locked_employee),
    )

    history.full_clean()
    history.save()

    return history


@transaction.atomic
def record_employee_eligibility_change(
    *,
    employee,
    effective_from,
    changed_by=None,
):
    """
    Close the previous eligibility period and create a new one.

    The Employee must already have been saved with the new eligibility
    values inside the same database transaction.
    """
    locked_employee = Employee.objects.select_for_update(
        of=("self",)
    ).get(pk=employee.pk)

    latest_history = (
        EmployeeEligibilityHistory.objects.select_for_update()
        .filter(employee_id=locked_employee.pk)
        .order_by("-effective_from", "-pk")
        .first()
    )

    if latest_history is None:
        raise ValidationError(
            "Cannot change eligibility because the employee has no "
            "existing eligibility-history record."
        )

    current_values = _get_employee_eligibility_values(
        locked_employee
    )

    previous_values = {
        "organization_id": latest_history.organization_id,
        "joining_date": latest_history.joining_date,
        "probation_end_date": latest_history.probation_end_date,
        "employee_type": latest_history.employee_type,
        "department_id": latest_history.department_id,
        "designation_id": latest_history.designation_id,
    }

    # No new history row is needed if eligibility has not changed.
    if current_values == previous_values:
        return latest_history

    if latest_history.effective_until is not None:
        raise ValidationError(
            "The latest eligibility-history record is already closed. "
            "A new eligibility period cannot be added."
        )

    if effective_from <= latest_history.effective_from:
        raise ValidationError(
            "The effective-from date must be later than the previous "
            "eligibility period's effective-from date."
        )

    previous_end_date = effective_from - timedelta(days=1)

    if previous_end_date < latest_history.effective_from:
        raise ValidationError(
            "The new effective date would create an invalid "
            "eligibility-history period."
        )

    latest_history.effective_until = previous_end_date
    latest_history.full_clean()
    latest_history.save(update_fields=["effective_until"])

    new_history = EmployeeEligibilityHistory(
        employee=locked_employee,
        effective_from=effective_from,
        effective_until=None,
        changed_by=changed_by,
        source=EmployeeEligibilityHistory.Source.ADMIN_UPDATE,
        **current_values,
    )

    new_history.full_clean()
    new_history.save()

    return new_history


def get_employee_eligibility_for_date(
    *,
    employee,
    eligibility_date,
):
    """
    Return the employee's eligibility snapshot applicable on a date.

    Missing or overlapping history is treated as a data-integrity error.
    """
    matching_records = (
        EmployeeEligibilityHistory.objects.filter(
            employee_id=employee.pk,
            organization_id=employee.organization_id,
            effective_from__lte=eligibility_date,
        )
        .filter(
            Q(effective_until__isnull=True)
            | Q(effective_until__gte=eligibility_date)
        )
        .order_by("-effective_from", "-pk")
    )

    records = list(matching_records[:2])

    if not records:
        first_history = (
            EmployeeEligibilityHistory.objects.filter(
                employee_id=employee.pk,
                organization_id=employee.organization_id,
            )
            .order_by("effective_from", "pk")
            .first()
        )

        # Before the employee's joining date, there is no entitlement.
        if (
            first_history is not None
            and eligibility_date < first_history.joining_date
        ):
            return None

        raise ValidationError(
            f"No employee eligibility history exists for employee "
            f"{employee.pk} on {eligibility_date}."
        )

    if len(records) > 1:
        raise ValidationError(
            f"Overlapping employee eligibility history exists for "
            f"employee {employee.pk} on {eligibility_date}."
        )

    return records[0]
