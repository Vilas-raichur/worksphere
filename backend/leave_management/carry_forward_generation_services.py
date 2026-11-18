# leave_management/carry_forward_generation_services.py

import calendar
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from attendance.services import (
    _working_dates,
    get_attendance_policy,
)

from employees.models import Employee

from employees.eligibility_services import (
    get_employee_eligibility_for_date,
)

from leave_management.models import (
    LeaveBalance,
    LeaveBalanceTransaction,
    LeaveCarryForwardLot,
    LeavePolicyRule,
    LeaveRequest,
)

from leave_management.leave_periods import (
    get_completed_carry_forward_intervals,
    get_leave_year_period,
)

from leave_management.policy_selection import (
    select_applicable_leave_rules,
)

from leave_management.carry_forward_services import (
    reconcile_carry_forward_consumption,
)


ZERO = Decimal("0.00")
ONE = Decimal("1.00")


def _add_months(anchor_date, months):
    month_index = anchor_date.month - 1 + months
    year = anchor_date.year + month_index // 12
    month = month_index % 12 + 1

    day = min(
        anchor_date.day,
        calendar.monthrange(year, month)[1],
    )

    return date(year, month, day)


def _calendar_months(start_date, end_date):
    year = start_date.year
    month = start_date.month

    while (year, month) <= (end_date.year, end_date.month):
        yield year, month

        if month == 12:
            year += 1
            month = 1
        else:
            month += 1


def _get_candidate_carry_forward_rules(
    *,
    employee,
    balance,
):
    """
    Find published, active carry-forward rules for this leave type,
    independently of whether monthly accrual transactions exist.
    """
    return list(
        LeavePolicyRule.objects.filter(
            version__policy__organization_id=employee.organization_id,
            version__policy__is_active=True,
            version__status="PUBLISHED",
            version__effective_from__lte=balance.period_end,
            is_active=True,
            leave_type_id=balance.leave_type_id,
            leave_type__organization_id=employee.organization_id,
            leave_type__is_active=True,
            allow_carry_forward=True,
        )
        .filter(
            Q(version__effective_until__isnull=True)
            | Q(version__effective_until__gte=balance.period_start)
        )
        .select_related(
            "version",
            "leave_type",
        )
        .order_by("priority", "id")
    )



def _get_expected_accruals(
    *,
    employee,
    leave_type_id,
    interval_start,
    interval_end,
):
    """
    Return expected monthly accrual dates and historically applicable rules.

    Eligibility is selected separately for each accrual date.
    Missing or overlapping history raises ValidationError.
    """
    expected = []

    for year, month in _calendar_months(
        interval_start,
        interval_end,
    ):
        month_start = date(year, month, 1)
        month_end = date(
            year,
            month,
            calendar.monthrange(year, month)[1],
        )

        for accrual_date in (month_start, month_end):
            if not interval_start <= accrual_date <= interval_end:
                continue

            eligibility = get_employee_eligibility_for_date(
                employee=employee,
                eligibility_date=accrual_date,
            )

            # No accrual is expected before the employee joins.
            if eligibility is None:
                continue

            if accrual_date < eligibility.joining_date:
                continue

            in_probation = (
                eligibility.probation_end_date is not None
                and accrual_date <= eligibility.probation_end_date
            )

            selected_rules = select_applicable_leave_rules(
                organization_id=eligibility.organization_id,
                allocation_date=accrual_date,
                department_id=eligibility.department_id,
                designation_id=eligibility.designation_id,
                employee_type=eligibility.employee_type,
                in_probation=in_probation,
            )

            rule = selected_rules.get(leave_type_id)

            if rule is None or rule.monthly_accrual_days <= ZERO:
                continue

            expected_date = (
                month_start
                if rule.accrual_timing == "MONTH_START"
                else month_end
            )

            if expected_date != accrual_date:
                continue

            expected.append((accrual_date, rule))

    return expected


def _get_active_carry_forward_consumption_dates(
    *,
    employee,
    leave_type_id,
    through_date,
):
    """
    Return dates already supplied by active carry-forward lots.

    Reversed consumption records are excluded.
    """
    consumptions = (
        LeaveCarryForwardLot.objects.filter(
            balance__employee=employee,
            balance__leave_type_id=leave_type_id,
            carried_forward_on__lte=through_date,
        )
        .values_list("id", flat=True)
    )

    from leave_management.models import (
        LeaveCarryForwardConsumption,
        LeaveCarryForwardConsumptionReversal,
    )

    rows = (
        LeaveCarryForwardConsumption.objects.filter(
            lot_id__in=consumptions,
            consumed_on__lte=through_date,
        )
        .select_related("leave_request")
    )

    reversed_ids = set(
        LeaveCarryForwardConsumptionReversal.objects.filter(
            consumption_id__in=rows.values_list("id", flat=True)
        ).values_list("consumption_id", flat=True)
    )

    return {
        row.consumed_on
        for row in rows
        if row.pk not in reversed_ids
    }


def _get_approved_ordinary_usage_dates(
    *,
    employee,
    leave_type_id,
    balance,
    through_date,
    carry_forward_dates,
):
    """
    Return approved working dates that were not allocated to
    carry-forward lots.

    These dates consume ordinary accruals.
    """
    attendance_policy = get_attendance_policy(employee)

    requests = LeaveRequest.objects.filter(
        organization_id=employee.organization_id,
        employee=employee,
        leave_type_id=leave_type_id,
        status=LeaveRequest.Status.APPROVED,
        start_date__lte=through_date,
        end_date__gte=balance.period_start,
    ).order_by("start_date", "end_date", "id")

    usage_dates = []

    for request in requests:
        overlap_start = max(
            request.start_date,
            balance.period_start,
        )
        overlap_end = min(
            request.end_date,
            through_date,
        )

        working_dates = _working_dates(
            employee,
            attendance_policy,
            overlap_start,
            overlap_end,
        )

        for working_date in working_dates:
            if working_date not in carry_forward_dates:
                usage_dates.append(working_date)

    return sorted(usage_dates)


def _calculate_unused_accruals_by_rule(
    *,
    employee,
    balance,
    interval_start,
    interval_end,
    carry_forward_dates,
):
    """
    Calculate remaining ordinary accruals across all policy rules.

    Ordinary entitlement is consumed FIFO across policy changes.
    Existing carry-forward grants are removed from their original
    source accruals so the same entitlement cannot be granted twice.
    """
    transactions = list(
        LeaveBalanceTransaction.objects.filter(
            organization_id=employee.organization_id,
            employee=employee,
            leave_type_id=balance.leave_type_id,
            balance=balance,
            transaction_type=(
                LeaveBalanceTransaction.TransactionType.ACCRUAL
            ),
            effective_date__lte=interval_end,
        )
        .select_related("policy_rule", "policy_version")
        .order_by("effective_date", "created_at", "id")
    )

    unsupported_types = {
        LeaveBalanceTransaction.TransactionType.ALLOCATION,
        LeaveBalanceTransaction.TransactionType.ADJUSTMENT,
        LeaveBalanceTransaction.TransactionType.LEAVE_DEBIT,
        LeaveBalanceTransaction.TransactionType.LEAVE_CREDIT,
    }

    unsupported_transactions = (
        LeaveBalanceTransaction.objects.filter(
            organization_id=employee.organization_id,
            employee=employee,
            leave_type_id=balance.leave_type_id,
            balance=balance,
            transaction_type__in=unsupported_types,
            effective_date__lte=interval_end,
        )
    )

    if unsupported_transactions.exists():
        raise ValidationError(
            "Carry-forward generation cannot safely calculate this "
            "balance because it contains opening allocations, "
            "adjustments, or leave debit/credit transactions. "
            "These transactions need explicit FIFO accounting first."
        )

    if any(txn.days < ZERO for txn in transactions):
        raise ValidationError(
            "Negative accrual transactions require explicit reversal "
            "accounting before carry-forward generation."
        )

    tranches = []

    for txn in transactions:
        if txn.days <= ZERO:
            continue

        if txn.policy_rule_id is None or txn.policy_version_id is None:
            raise ValidationError(
                "A positive accrual has no associated policy rule "
                "or policy version. Carry-forward cannot be calculated."
            )

        tranches.append(
            {
                "transaction": txn,
                "remaining": txn.days,
            }
        )

    if not tranches:
        return {}

    # Existing lots permanently transfer their original grants out
    # of ordinary entitlement, even if the lots were later consumed
    # or expired.
    existing_lots = list(
        LeaveCarryForwardLot.objects.filter(
            balance=balance,
            source_period_end__lte=interval_end,
        ).order_by(
            "source_period_start",
            "source_period_end",
            "carried_forward_on",
            "id",
        )
    )

    for lot in existing_lots:
        matching_tranches = [
            item
            for item in tranches
            if (
                item["transaction"].policy_rule_id == lot.policy_rule_id
                and lot.source_period_start
                <= item["transaction"].effective_date
                <= lot.source_period_end
            )
        ]

        remaining_grant = lot.granted_days

        for tranche in matching_tranches:
            if remaining_grant <= ZERO:
                break

            deduction = min(
                tranche["remaining"],
                remaining_grant,
            )

            tranche["remaining"] -= deduction
            remaining_grant -= deduction

        if remaining_grant > ZERO:
            raise ValidationError(
                "An existing carry-forward grant cannot be matched "
                f"to its source accruals. Lot ID: {lot.pk}."
            )

    usage_dates = _get_approved_ordinary_usage_dates(
        employee=employee,
        leave_type_id=balance.leave_type_id,
        balance=balance,
        through_date=interval_end,
        carry_forward_dates=carry_forward_dates,
    )

    # Ordinary leave usage consumes the oldest available accrual
    # across every policy rule, not separately per rule.
    for usage_date in usage_dates:
        remaining_usage = ONE

        for tranche in tranches:
            txn = tranche["transaction"]

            if txn.effective_date > usage_date:
                continue

            if tranche["remaining"] <= ZERO:
                continue

            deduction = min(
                tranche["remaining"],
                remaining_usage,
            )

            tranche["remaining"] -= deduction
            remaining_usage -= deduction

            if remaining_usage <= ZERO:
                break

        if remaining_usage > ZERO:
            raise ValidationError(
                "Approved leave could not be attributed to available "
                "ordinary accruals. "
                f"Leave date: {usage_date}. "
                "Carry-forward generation has been stopped."
            )

    # Return only unused accruals belonging to the interval currently
    # being processed, grouped by their original policy rule.
    unused_by_rule = defaultdict(lambda: ZERO)

    for tranche in tranches:
        txn = tranche["transaction"]

        if (
            interval_start
            <= txn.effective_date
            <= interval_end
        ):
            unused_by_rule[txn.policy_rule_id] += (
                tranche["remaining"]
            )

    return dict(unused_by_rule)


def _get_completed_intervals(
    organization,
    first_accrual_date,
    processing_date,
    interval_months,
):
    """
    Discover completed intervals across all leave years since
    the first accrual date.
    """
    intervals = []

    leave_year_start, leave_year_end = get_leave_year_period(
        organization,
        first_accrual_date,
    )

    while leave_year_start <= processing_date:
        next_leave_year_start = leave_year_end + timedelta(days=1)

        if next_leave_year_start <= processing_date:
            check_date = next_leave_year_start
        else:
            check_date = processing_date

        completed = get_completed_carry_forward_intervals(
            organization,
            check_date,
            interval_months,
        )

        intervals.extend(completed)

        leave_year_start, leave_year_end = get_leave_year_period(
            organization,
            next_leave_year_start,
        )

    # Keep only intervals beginning on or after the first accrual date.
    return [
        interval
        for interval in dict.fromkeys(intervals)
        if interval[0] >= first_accrual_date
    ]


@transaction.atomic
def generate_carry_forward_lots(
    *,
    employee,
    processing_date=None,
    dry_run=False,
):
    """
    Generate carry-forward lots for one active employee.

    The function does not increase LeaveBalance.entitled_days.
    """
    if processing_date is None:
        processing_date = timezone.localdate()

    employee = (
        Employee.objects.select_for_update(of=("self",))
        .select_related("organization", "department", "designation")
        .get(pk=employee.pk)
    )

    if employee.status != Employee.Status.ACTIVE:
        return {
            "employee_id": employee.pk,
            "created": 0,
            "skipped": 0,
            "failed": 0,
            "results": [],
        }

    balances = (
        LeaveBalance.objects.filter(
            organization_id=employee.organization_id,
            employee=employee,
        )
        .select_related("leave_type")
        .order_by("period_start", "leave_type_id")
    )

    results = []
    created_count = 0
    skipped_count = 0
    failed_count = 0

    for balance in balances:
        candidate_rules = _get_candidate_carry_forward_rules(
            employee=employee,
            balance=balance,
        )

        for rule in candidate_rules:
            if not rule.carry_forward_interval_months:
                continue

            try:
                intervals = _get_completed_intervals(
                    employee.organization,
                    balance.period_start,
                    processing_date,
                    rule.carry_forward_interval_months,
                )

                for interval_start, interval_end in intervals:
                    if interval_end > processing_date - timedelta(days=1):
                        continue

                    # Do not create a lot outside its balance period.
                    if (
                        interval_start < balance.period_start
                        or interval_end > balance.period_end
                    ):
                        continue

                    idempotency_key = (
                        f"carry-forward:"
                        f"{employee.pk}:"
                        f"{balance.leave_type_id}:"
                        f"{rule.pk}:"
                        f"{interval_start.isoformat()}:"
                        f"{interval_end.isoformat()}"
                    )

                    existing_lot = LeaveCarryForwardLot.objects.filter(
                        idempotency_key=idempotency_key,
                    ).first()

                    if existing_lot:
                        skipped_count += 1
                        results.append(
                            {
                                "interval": (
                                    interval_start,
                                    interval_end,
                                ),
                                "rule_id": rule.pk,
                                "status": "already_generated",
                                "lot_id": existing_lot.pk,
                            }
                        )
                        continue

                    expected = _get_expected_accruals(
                        employee=employee,
                        leave_type_id=balance.leave_type_id,
                        interval_start=interval_start,
                        interval_end=interval_end,
                    )

                    missing = []

                    for accrual_date, expected_rule in expected:
                        found = LeaveBalanceTransaction.objects.filter(
                            organization_id=employee.organization_id,
                            employee=employee,
                            balance=balance,
                            leave_type_id=balance.leave_type_id,
                            transaction_type=(
                                LeaveBalanceTransaction.TransactionType.ACCRUAL
                            ),
                            policy_rule=expected_rule,
                            effective_date=accrual_date,
                        ).exists()

                        if not found:
                            missing.append(
                                f"{accrual_date} (rule {expected_rule.pk})"
                            )

                    if missing:
                        raise ValidationError(
                            "Missing expected monthly accruals: "
                            + ", ".join(missing)
                        )

                    # Reconcile existing lots before calculating ordinary usage.
                    reconcile_carry_forward_consumption(
                        employee=employee,
                        leave_type_id=balance.leave_type_id,
                        processing_date=processing_date,
                    )

                    carry_forward_dates = (
                        _get_active_carry_forward_consumption_dates(
                            employee=employee,
                            leave_type_id=balance.leave_type_id,
                            through_date=interval_end,
                        )
                    )

                    unused_by_rule = _calculate_unused_accruals_by_rule(
                        employee=employee,
                        balance=balance,
                        interval_start=interval_start,
                        interval_end=interval_end,
                        carry_forward_dates=carry_forward_dates,
                    )

                    unused_days = unused_by_rule.get(
                        rule.pk,
                        ZERO,
                    )

                    grant_days = min(
                        unused_days,
                        rule.carry_forward_limit_days,
                    )

                    if grant_days <= ZERO:
                        skipped_count += 1
                        results.append(
                            {
                                "interval": (
                                    interval_start,
                                    interval_end,
                                ),
                                "rule_id": rule.pk,
                                "status": "no_unused_days",
                                "unused_days": unused_days,
                            }
                        )
                        continue

                    carried_forward_on = interval_end + timedelta(days=1)

                    expires_on = _add_months(
                        carried_forward_on,
                        rule.carry_forward_expiry_months,
                    )

                    if dry_run:
                        results.append(
                            {
                                "interval": (
                                    interval_start,
                                    interval_end,
                                ),
                                "rule_id": rule.pk,
                                "status": "dry_run",
                                "grant_days": grant_days,
                                "expires_on": expires_on,
                            }
                        )
                        continue

                    lot = LeaveCarryForwardLot(
                        balance=balance,
                        policy_version=rule.version,
                        policy_rule=rule,
                        source_period_start=interval_start,
                        source_period_end=interval_end,
                        carried_forward_on=carried_forward_on,
                        expires_on=expires_on,
                        granted_days=grant_days,
                        remaining_days=grant_days,
                        idempotency_key=idempotency_key,
                    )

                    lot.full_clean()
                    lot.save()

                    created_count += 1

                    results.append(
                        {
                            "interval": (
                                interval_start,
                                interval_end,
                            ),
                            "rule_id": rule.pk,
                            "status": "created",
                            "lot_id": lot.pk,
                            "grant_days": grant_days,
                            "expires_on": expires_on,
                        }
                    )

            except Exception:
                # Abort the employee's complete generation transaction.
                # Do not swallow database errors inside an atomic block.
                raise

    result = {
        "employee_id": employee.pk,
        "created": created_count,
        "skipped": skipped_count,
        "failed": failed_count,
        "results": results,
    }

    # The service is wrapped in transaction.atomic().
    # Roll back all writes, including reconciliation writes,
    # when running in dry-run mode.
    if dry_run:
        transaction.set_rollback(True)

    return result