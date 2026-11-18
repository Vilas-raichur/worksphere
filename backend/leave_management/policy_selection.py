from django.db import models
from django.core.exceptions import ValidationError

from leave_management.models import (
    LeavePolicyRule,
    LeavePolicyVersion,
)


def select_applicable_leave_rules(
    *,
    organization_id,
    allocation_date,
    department_id,
    designation_id,
    employee_type,
    in_probation,
):
    """
    Select one applicable rule per leave type.

    A smaller priority number has higher precedence.
    Equal-priority matches are treated as ambiguous.
    This function does not create leave balances.
    """

    versions = LeavePolicyVersion.objects.filter(
        policy__organization_id=organization_id,
        policy__is_active=True,
        status=LeavePolicyVersion.Status.PUBLISHED,
        effective_from__lte=allocation_date,
    ).filter(
        models.Q(effective_until__isnull=True)
        | models.Q(effective_until__gte=allocation_date)
    )

    rules = (
        LeavePolicyRule.objects.filter(
            version__in=versions,
            is_active=True,
            leave_type__is_active=True,
            leave_type__organization_id=organization_id,
        )
        .select_related("leave_type", "version")
        .order_by("priority", "id")
    )

    selected = {}

    for rule in rules:
        if (
            rule.department_id is not None
            and rule.department_id != department_id
        ):
            continue

        if (
            rule.designation_id is not None
            and rule.designation_id != designation_id
        ):
            continue

        if rule.employee_type and (
            rule.employee_type != employee_type
        ):
            continue

        if (
            rule.probation_condition
            == LeavePolicyRule.ProbationCondition.IN_PROBATION
            and not in_probation
        ):
            continue

        if (
            rule.probation_condition
            == LeavePolicyRule.ProbationCondition.COMPLETED
            and in_probation
        ):
            continue

        existing = selected.get(rule.leave_type_id)

        if existing is None:
            selected[rule.leave_type_id] = rule
            continue

        if existing.priority == rule.priority:
            raise ValidationError({
                "rules": (
                    "Ambiguous leave policy configuration for "
                    f"leave type {rule.leave_type_id}: "
                    f"rules {existing.pk} and {rule.pk} "
                    "have equal priority."
                )
            })

    return selected
