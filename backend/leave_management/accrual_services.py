import calendar
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction

from employees.models import Employee
from leave_management.models import (
    LeaveBalance,
    LeaveBalanceTransaction,
    LeavePolicyRule,
    LeavePolicyVersion,
)


def _get_existing_accrual(idempotency_key):
    return (
        LeaveBalanceTransaction.objects
        .filter(idempotency_key=idempotency_key)
        .first()
    )


def _validate_existing_accrual(
    existing_transaction,
    *,
    employee,
    rule,
    accrual_amount,
    accrual_date,
    period_start,
    period_end,
):
    if existing_transaction is None:
        return None

    if (
        existing_transaction.employee_id != employee.pk
        or existing_transaction.organization_id != employee.organization_id
        or existing_transaction.leave_type_id != rule.leave_type_id
        or existing_transaction.days != accrual_amount
        or existing_transaction.effective_date != accrual_date
        or existing_transaction.policy_rule_id != rule.pk
        or existing_transaction.policy_version_id != rule.version_id
        or existing_transaction.balance.period_start != period_start
        or existing_transaction.balance.period_end != period_end
        or existing_transaction.transaction_type
        != LeaveBalanceTransaction.TransactionType.ACCRUAL
    ):
        raise ValidationError(
            "The accrual idempotency key already exists "
            "with different transaction details."
        )

    return existing_transaction


@transaction.atomic
def accrue_monthly_leave(
    *,
    employee,
    rule,
    accrual_date,
    period_start,
    period_end,
):
    """
    Credit one month's leave accrual for an employee.

    The caller must pass the applicable rule selected by
    select_applicable_leave_rules().

    period_start and period_end identify the balance period.
    No upfront or annual entitlement is created.
    """

    if employee.pk is None:
        raise ValidationError("A saved employee record is required.")

    # Serialize accrual processing for this employee.
    # Unlike the attendance helper, this does not require a login account.
    employee = (
        Employee.objects.select_for_update()
        .get(pk=employee.pk)
    )

    if employee.status != Employee.Status.ACTIVE:
        raise ValidationError(
            "Only active employees can receive leave accrual."
        )

    if employee.organization_id is None:
        raise ValidationError(
            "The employee must belong to an organization."
        )

    if period_end < period_start:
        raise ValidationError(
            "The balance period end cannot be before its start."
        )

    if not period_start <= accrual_date <= period_end:
        raise ValidationError(
            "The accrual date must fall inside the balance period."
        )

    if not isinstance(rule, LeavePolicyRule) or rule.pk is None:
        raise ValidationError(
            "A saved, applicable leave policy rule is required."
        )

    rule = (
        LeavePolicyRule.objects.select_related(
            "version",
            "version__policy",
            "leave_type",
        )
        .get(pk=rule.pk)
    )

    version = rule.version
    policy = version.policy

    if not rule.is_active:
        raise ValidationError(
            "The selected policy rule is inactive."
        )

    if version.status != LeavePolicyVersion.Status.PUBLISHED:
        raise ValidationError(
            "Monthly accrual requires a published policy version."
        )

    if not policy.is_active:
        raise ValidationError(
            "The selected leave policy is inactive."
        )

    if (
        policy.organization_id != employee.organization_id
        or rule.leave_type.organization_id != employee.organization_id
    ):
        raise ValidationError(
            "The policy, leave type and employee must belong "
            "to the same organization."
        )

    if not rule.leave_type.is_active:
        raise ValidationError(
            "The selected leave type is inactive."
        )

    if accrual_date < version.effective_from:
        raise ValidationError(
            "The policy version is not effective on the accrual date."
        )

    if (
        version.effective_until is not None
        and accrual_date > version.effective_until
    ):
        raise ValidationError(
            "The policy version has expired on the accrual date."
        )

    # Confirm that the rule matches the employee.
    if (
        rule.department_id is not None
        and rule.department_id != employee.department_id
    ):
        raise ValidationError(
            "The selected policy rule does not match "
            "the employee's department."
        )

    if (
        rule.designation_id is not None
        and rule.designation_id != employee.designation_id
    ):
        raise ValidationError(
            "The selected policy rule does not match "
            "the employee's designation."
        )

    if (
        rule.employee_type
        and rule.employee_type != employee.employee_type
    ):
        raise ValidationError(
            "The selected policy rule does not match "
            "the employee's employment type."
        )

    in_probation = (
        employee.probation_end_date is not None
        and accrual_date <= employee.probation_end_date
    )

    if (
        rule.probation_condition
        == LeavePolicyRule.ProbationCondition.IN_PROBATION
        and not in_probation
    ):
        raise ValidationError(
            "The selected policy rule requires an employee "
            "who is in probation."
        )

    if (
        rule.probation_condition
        == LeavePolicyRule.ProbationCondition.COMPLETED
        and in_probation
    ):
        raise ValidationError(
            "The selected policy rule requires completed probation."
        )

    # Validate the configured monthly accrual date.
    if rule.accrual_timing == LeavePolicyRule.AccrualTiming.MONTH_START:
        if accrual_date.day != 1:
            raise ValidationError(
                "This rule accrues leave only on the first day of a month."
            )

    elif rule.accrual_timing == LeavePolicyRule.AccrualTiming.MONTH_END:
        last_day = calendar.monthrange(
            accrual_date.year,
            accrual_date.month,
        )[1]

        if accrual_date.day != last_day:
            raise ValidationError(
                "This rule accrues leave only on the last day of a month."
            )

    else:
        raise ValidationError(
            "Unsupported monthly accrual timing."
        )

    accrual_amount = rule.monthly_accrual_days

    if accrual_amount <= Decimal("0.00"):
        return None

    idempotency_key = (
        f"monthly-accrual:{employee.pk}:"
        f"{rule.pk}:{accrual_date:%Y-%m}"
    )

    existing_transaction = _get_existing_accrual(
        idempotency_key
    )

    existing_transaction = _validate_existing_accrual(
        existing_transaction,
        employee=employee,
        rule=rule,
        accrual_amount=accrual_amount,
        accrual_date=accrual_date,
        period_start=period_start,
        period_end=period_end,
    )

    if existing_transaction is not None:
        return existing_transaction

    balance, _ = LeaveBalance.objects.get_or_create(
        organization_id=employee.organization_id,
        employee=employee,
        leave_type=rule.leave_type,
        period_start=period_start,
        period_end=period_end,
        defaults={
            "entitled_days": Decimal("0.00"),
        },
    )

    balance = (
        LeaveBalance.objects.select_for_update()
        .get(pk=balance.pk)
    )

    # Check again after obtaining the balance lock.
    existing_transaction = _get_existing_accrual(
        idempotency_key
    )

    existing_transaction = _validate_existing_accrual(
        existing_transaction,
        employee=employee,
        rule=rule,
        accrual_amount=accrual_amount,
        accrual_date=accrual_date,
        period_start=period_start,
        period_end=period_end,
    )

    if existing_transaction is not None:
        return existing_transaction

    balance.full_clean()

    leave_transaction = LeaveBalanceTransaction.objects.create(
        organization_id=employee.organization_id,
        employee=employee,
        leave_type=rule.leave_type,
        balance=balance,
        transaction_type=(
            LeaveBalanceTransaction.TransactionType.ACCRUAL
        ),
        days=accrual_amount,
        effective_date=accrual_date,
        policy_version=version,
        policy_rule=rule,
        idempotency_key=idempotency_key,
        description=(
            f"Monthly accrual under {policy.code}, "
            f"version {version.version_number}."
        ),
    )

    balance.entitled_days += accrual_amount
    balance.save(
        update_fields=["entitled_days", "updated_at"]
    )

    return leave_transaction