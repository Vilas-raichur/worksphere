
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from leave_management.models import (
    LeavePolicy,
    LeavePolicyRule,
    LeavePolicyVersion,
    LeaveType,
)

from accounts.models import Organization

from leave_management.policy_permissions import can_manage_leave_policies


def require_policy_manager(user):
    if not can_manage_leave_policies(user):
        raise PermissionError(
            "You are not authorized to manage leave policies."
        )

    return user.worksphere_profile


def _get_policy(profile, policy_id):
    try:
        return LeavePolicy.objects.get(
            pk=policy_id,
            organization_id=profile.organization_id,
        )
    except LeavePolicy.DoesNotExist:
        raise ValidationError(
            {"policy_id": "Leave policy was not found."}
        )


@transaction.atomic
def create_leave_policy(*, user, code, name, description=""):
    profile = require_policy_manager(user)

    code = code.strip().upper()
    name = name.strip()

    if not code or not name:
        raise ValidationError(
            "Policy code and name are required."
        )

    policy = LeavePolicy(
        organization=profile.organization,
        code=code,
        name=name,
        description=description,
    )
    policy.full_clean()
    policy.save()

    return policy


@transaction.atomic
def create_policy_version(
    *, user, policy_id, version_number,
    effective_from, effective_until=None
):
    profile = require_policy_manager(user)
    policy = _get_policy(profile, policy_id)

    if not policy.is_active:
        raise ValidationError(
            {"policy_id": "The leave policy is inactive."}
        )

    version = LeavePolicyVersion(
        policy=policy,
        version_number=version_number,
        effective_from=effective_from,
        effective_until=effective_until,
    )
    version.full_clean()
    version.save()

    return version


@transaction.atomic
def create_policy_rule(
    *,
    user,
    version_id,
    leave_type_id,
    monthly_accrual_days,
    accrual_timing,
    department_id=None,
    designation_id=None,
    employee_type="",
    probation_condition=LeavePolicyRule.ProbationCondition.ANY,
    priority=100,
    allow_carry_forward=False,
    carry_forward_limit_days=0,
    carry_forward_interval_months=None,
    carry_forward_expiry_months=None,
):
    profile = require_policy_manager(user)

    try:
        version = LeavePolicyVersion.objects.select_for_update().get(
            pk=version_id,
            policy__organization_id=profile.organization_id,
        )
    except LeavePolicyVersion.DoesNotExist:
        raise ValidationError(
            {"version_id": "Policy version was not found."}
        )

    if version.status != LeavePolicyVersion.Status.DRAFT:
        raise ValidationError(
            {"version_id": "Published versions cannot be edited."}
        )

    try:
        leave_type = LeaveType.objects.get(
            pk=leave_type_id,
            organization_id=profile.organization_id,
            is_active=True,
        )
    except LeaveType.DoesNotExist:
        raise ValidationError(
            {"leave_type_id": "Active leave type was not found."}
        )

    rule = LeavePolicyRule(
        version=version,
        leave_type=leave_type,
        department_id=department_id,
        designation_id=designation_id,
        employee_type=employee_type.strip(),
        probation_condition=probation_condition,
        priority=priority,
        monthly_accrual_days=monthly_accrual_days,
        accrual_timing=accrual_timing,
        allow_carry_forward=allow_carry_forward,
        carry_forward_limit_days=carry_forward_limit_days,
        carry_forward_interval_months=carry_forward_interval_months,
        carry_forward_expiry_months=carry_forward_expiry_months,
    )
    if department_id is not None:
        from employees.models import Department

        if not Department.objects.filter(
            pk=department_id,
            is_active=True,
        ).exists():
            raise ValidationError({
                "department_id": "Active department was not found."
            })

    if designation_id is not None:
        from employees.models import Designation

        if not Designation.objects.filter(
            pk=designation_id,
            is_active=True,
        ).exists():
            raise ValidationError({
                "designation_id": "Active designation was not found."
            })

    rule.full_clean()
    rule.save()
    return rule



def _conditions_overlap(first, second):
    """
    Return True when two rules can match the same employee.

    A null department/designation or empty employee type
    matches all values of that dimension.
    """

    def matches(a, b, wildcard):
        return a == wildcard or b == wildcard or a == b

    return (
        matches(first.department_id, second.department_id, None)
        and matches(
            first.designation_id,
            second.designation_id,
            None,
        )
        and matches(
            first.employee_type,
            second.employee_type,
            "",
        )
        and matches(
            first.probation_condition,
            second.probation_condition,
            LeavePolicyRule.ProbationCondition.ANY,
        )
    )


def validate_policy_rule_conflicts(rules):
    """
    Reject overlapping eligibility rules for the same
    leave type when they have the same priority.

    Rules with different priorities are not rejected here.
    Their precedence must be handled by the allocation
    engine before that engine is activated.
    """

    for index, first in enumerate(rules):
        for second in rules[index + 1:]:
            if first.leave_type_id != second.leave_type_id:
                continue

            if first.priority != second.priority:
                continue

            if _conditions_overlap(first, second):
                raise ValidationError({
                    "rules": (
                        "Conflicting eligibility rules exist "
                        "for the same leave type and priority. "
                        f"Rule IDs: {first.pk} and {second.pk}."
                    )
                })



def _effective_date_ranges_overlap(first, second):
    """
    Return True when two policy version date ranges overlap.

    An effective_until value of None represents an open-ended
    date range.
    """
    first_ends_after_second_starts = (
        first.effective_until is None
        or second.effective_from <= first.effective_until
    )

    second_ends_after_first_starts = (
        second.effective_until is None
        or first.effective_from <= second.effective_until
    )

    return (
        first_ends_after_second_starts
        and second_ends_after_first_starts
    )


def validate_published_policy_rule_conflicts(*, version, rules):
    """
    Reject draft rules that conflict with active rules belonging
    to already-published policies in the same organization.

    Rules conflict when they have:
    - The same leave type.
    - The same priority.
    - Overlapping eligibility conditions.
    - Overlapping policy-version effective dates.
    """

    for draft_rule in rules:
        published_rules = (
            LeavePolicyRule.objects
            .filter(
                is_active=True,
                leave_type_id=draft_rule.leave_type_id,
                version__status=LeavePolicyVersion.Status.PUBLISHED,
                version__policy__organization_id=(
                    version.policy.organization_id
                ),
            )
            .exclude(
                version__policy_id=version.policy_id,
            )
            .select_related("version")
        )

        for published_rule in published_rules:
            if draft_rule.priority != published_rule.priority:
                continue

            if not _conditions_overlap(
                draft_rule,
                published_rule,
            ):
                continue

            if not _effective_date_ranges_overlap(
                version,
                published_rule.version,
            ):
                continue

            raise ValidationError({
                "rules": (
                    "A conflicting rule already exists in "
                    "another published policy for this organization. "
                    f"Draft rule ID: {draft_rule.pk}; "
                    f"published rule ID: {published_rule.pk}."
                )
            })


@transaction.atomic
def publish_policy_version(*, user, version_id):
    profile = require_policy_manager(user)

    # Serialize policy publication within this organization.
    # The lock remains held until this transaction completes.
    Organization.objects.select_for_update().get(
        pk=profile.organization_id
    )

    try:
        version = (
            LeavePolicyVersion.objects.select_for_update()
            .select_related("policy")
            .get(
                pk=version_id,
                policy__organization_id=profile.organization_id,
            )
        )
    except LeavePolicyVersion.DoesNotExist:
        raise ValidationError(
            {"version_id": "Policy version was not found."}
        )

    if version.status != LeavePolicyVersion.Status.DRAFT:
        raise ValidationError(
            {"version_id": "Only draft versions can be published."}
        )

    if not version.policy.is_active:
        raise ValidationError(
            {"policy_id": "The leave policy is inactive."}
        )

    rules = list(version.rules.filter(is_active=True))

    if not rules:
        raise ValidationError(
            {"rules": "At least one active rule is required."}
        )

    for rule in rules:
        rule.full_clean()

        if rule.department_id is not None:
            if not rule.department.is_active:
                raise ValidationError({
                    "rules": (
                        f"Rule {rule.pk} references "
                        "an inactive department."
                    )
                })

        if rule.designation_id is not None:
            if not rule.designation.is_active:
                raise ValidationError({
                    "rules": (
                        f"Rule {rule.pk} references "
                        "an inactive designation."
                    )
                })

        if not rule.leave_type.is_active:
            raise ValidationError({
                "rules": (
                    f"Rule {rule.pk} references "
                    "an inactive leave type."
                )
            })

    # First, check conflicts among rules in this draft version.
    validate_policy_rule_conflicts(rules)

    # Next, check conflicts against other published policies
    # belonging to the same organization.
    validate_published_policy_rule_conflicts(
        version=version,
        rules=rules,
    )

    # Preserve the existing same-policy version-overlap check.
    overlaps = LeavePolicyVersion.objects.filter(
        policy=version.policy,
        status=LeavePolicyVersion.Status.PUBLISHED,
    ).filter(
        Q(effective_until__isnull=True)
        | Q(effective_until__gte=version.effective_from)
    )

    if version.effective_until is not None:
        overlaps = overlaps.filter(
            effective_from__lte=version.effective_until,
        )

    if overlaps.exists():
        raise ValidationError(
            {
                "effective_from": (
                    "This version overlaps an existing "
                    "published policy version."
                )
            }
        )

    version.status = LeavePolicyVersion.Status.PUBLISHED
    version.published_by = profile
    version.published_at = timezone.now()
    version.full_clean()
    version.save(
        update_fields=[
            "status",
            "published_by",
            "published_at",
            "updated_at",
        ]
    )

    return version
