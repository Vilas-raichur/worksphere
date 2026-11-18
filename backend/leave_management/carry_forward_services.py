from collections import defaultdict
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from attendance.services import get_attendance_policy, _working_dates

from .models import (
    LeaveBalance,
    LeaveBalanceTransaction,
    LeaveCarryForwardConsumption,
    LeaveCarryForwardConsumptionReversal,
    LeaveCarryForwardLot,
    LeaveRequest,
)


ONE_DAY = Decimal("1.00")
ZERO_DAYS = Decimal("0.00")


@transaction.atomic
def reconcile_carry_forward_consumption(
    *,
    employee,
    leave_type_id,
    processing_date=None,
):
    """
    Reconcile carry-forward consumption for one employee and leave type.

    Existing consumption records are never modified or deleted.
    Invalid allocations are reversed using separate immutable records.

    FIFO allocation uses the earliest-expiring eligible lot first.
    Expired lots retain their historical consumption records.
    """

    employee.__class__.objects.select_for_update().get(
        pk=employee.pk
    )

    if processing_date is None:
        processing_date = timezone.localdate()

    lots = list(
        LeaveCarryForwardLot.objects.select_for_update()
        .filter(
            balance__employee=employee,
            balance__leave_type_id=leave_type_id,
        )
        .select_related(
            "balance",
            "policy_version",
            "policy_rule",
        )
        .order_by("expires_on", "carried_forward_on", "id")
    )

    if not lots:
        return {
            "employee_id": employee.pk,
            "leave_type_id": leave_type_id,
            "lots_processed": 0,
            "requests_processed": 0,
            "allocations_created": 0,
            "reversals_created": 0,
            "allocated_days": ZERO_DAYS,
            "restored_days": ZERO_DAYS,
        }

    lot_ids = [lot.pk for lot in lots]

    requests = list(
        LeaveRequest.objects.select_for_update()
        .filter(
            employee=employee,
            leave_type_id=leave_type_id,
            organization_id=lots[0].balance.organization_id,
            status=LeaveRequest.Status.APPROVED,
        )
        .order_by("start_date", "end_date", "id")
    )

    attendance_policy = get_attendance_policy(employee)

    desired_dates = defaultdict(set)

    for leave_request in requests:
        working_dates = _working_dates(
            employee,
            attendance_policy,
            leave_request.start_date,
            leave_request.end_date,
        )

        desired_dates[leave_request.pk].update(working_dates)

        desired_dates[leave_request.pk] = {
            leave_date
            for leave_date in desired_dates[leave_request.pk]
            if leave_date <= processing_date
        }

    consumptions = list(
        LeaveCarryForwardConsumption.objects.select_for_update()
        .filter(lot_id__in=lot_ids)
        .select_related(
            "lot",
            "leave_request",
        )
        .order_by("consumed_on", "id")
    )

    # Existing allocations with a reversal are historical events,
    # not active consumption.
    reversed_consumption_ids = set(
        LeaveCarryForwardConsumptionReversal.objects.filter(
            consumption_id__in=[
                item.pk for item in consumptions
            ]
        ).values_list(
            "consumption_id",
            flat=True,
        )
    )

    active_consumptions = [
        item
        for item in consumptions
        if item.pk not in reversed_consumption_ids
    ]

    # Determine which lots have already expired or are now due.
    expired_lot_ids = set(
        LeaveBalanceTransaction.objects.filter(
            balance_id__in=[
                lot.balance_id for lot in lots
            ],
            transaction_type=LeaveBalanceTransaction.TransactionType.EXPIRY,
            idempotency_key__in=[
                f"carry-forward-expiry:{lot.pk}"
                for lot in lots
            ],
        ).values_list(
            "idempotency_key",
            flat=True,
        )
    )

    expired_lot_ids = {
        lot.pk
        for lot in lots
        if (
            f"carry-forward-expiry:{lot.pk}" in expired_lot_ids
            or lot.expires_on <= processing_date
        )
    }

    lots_by_id = {
        lot.pk: lot
        for lot in lots
    }

    # Find active allocations that are no longer valid.
    # Allocations on expired lots are retained as historical usage.
    reversals_created = 0
    restored_days = ZERO_DAYS

    for consumption in active_consumptions:
        lot = lots_by_id[consumption.lot_id]

        if consumption.consumed_on > processing_date:
            continue

        if lot.pk in expired_lot_ids:
            continue

        request_dates = desired_dates.get(
            consumption.leave_request_id,
            set(),
        )

        allocation_is_valid = (
            consumption.consumed_on in request_dates
            and lot.carried_forward_on
            <= consumption.consumed_on
            < lot.expires_on
        )

        if allocation_is_valid:
            continue

        reversal_key = (
            f"carry-forward-reversal:{consumption.pk}"
        )

        reversal = LeaveCarryForwardConsumptionReversal(
            consumption=consumption,
            reversed_days=consumption.allocated_days,
            reason=(
                "Approved leave request changed or was cancelled."
            ),
            idempotency_key=reversal_key,
        )

        reversal.save()

        lot.remaining_days += consumption.allocated_days

        lot.save(
            update_fields=[
                "remaining_days",
                "updated_at",
            ]
        )

        reversals_created += 1
        restored_days += consumption.allocated_days

        # The allocation has now been reversed.
        reversed_consumption_ids.add(consumption.pk)

    # Rebuild the set of dates that already have active allocations.
    allocated_dates = set()

    for consumption in consumptions:
        if consumption.pk in reversed_consumption_ids:
            continue

        allocated_dates.add(
            (
                consumption.leave_request_id,
                consumption.consumed_on,
            )
        )

    allocations_created = 0
    total_allocated = ZERO_DAYS

    # Lots are already ordered by earliest expiry date.
    eligible_lots = [
        lot
        for lot in lots
        if (
            lot.pk not in expired_lot_ids
            and lot.remaining_days >= ONE_DAY
        )
    ]

    for leave_request in requests:
        for leave_date in sorted(
            desired_dates[leave_request.pk]
        ):
            allocation_key = (
                leave_request.pk,
                leave_date,
            )

            if allocation_key in allocated_dates:
                continue

            selected_lot = next(
                (
                    lot
                    for lot in eligible_lots
                    if (
                        lot.carried_forward_on
                        <= leave_date
                        < lot.expires_on
                        and lot.remaining_days >= ONE_DAY
                    )
                ),
                None,
            )

            if selected_lot is None:
                continue

            previous_count = (
                LeaveCarryForwardConsumption.objects.filter(
                    lot_id=selected_lot.pk,
                    leave_request_id=leave_request.pk,
                    consumed_on=leave_date,
                ).count()
            )

            idempotency_key = (
                f"carry-forward-consumption:"
                f"{selected_lot.pk}:"
                f"{leave_request.pk}:"
                f"{leave_date.isoformat()}:"
                f"{previous_count + 1}"
            )

            consumption = LeaveCarryForwardConsumption(
                lot=selected_lot,
                leave_request=leave_request,
                consumed_on=leave_date,
                allocated_days=ONE_DAY,
                idempotency_key=idempotency_key,
            )

            consumption.save()

            selected_lot.remaining_days -= ONE_DAY

            selected_lot.save(
                update_fields=[
                    "remaining_days",
                    "updated_at",
                ]
            )

            allocated_dates.add(allocation_key)

            allocations_created += 1
            total_allocated += ONE_DAY

    return {
        "employee_id": employee.pk,
        "leave_type_id": leave_type_id,
        "lots_processed": len(lots),
        "requests_processed": len(requests),
        "allocations_created": allocations_created,
        "reversals_created": reversals_created,
        "allocated_days": total_allocated,
        "restored_days": restored_days,
    }


@transaction.atomic
def expire_carry_forward_lot(
    *,
    lot_id,
    expiry_date=None,
):
    """
    Expire the unused days in one carry-forward lot.

    The expiry transaction, balance reduction and lot update
    are committed together or rolled back together.
    """

    if expiry_date is None:
        expiry_date = timezone.localdate()

    lot = (
        LeaveCarryForwardLot.objects
        .select_for_update()
        .get(pk=lot_id)
    )

    if expiry_date < lot.expires_on:
        return {
            "status": "not_due",
            "lot_id": lot.pk,
            "expired_days": ZERO_DAYS,
        }

    balance = (
        LeaveBalance.objects
        .select_for_update()
        .get(pk=lot.balance_id)
    )

    idempotency_key = f"carry-forward-expiry:{lot.pk}"

    existing_transaction = (
        LeaveBalanceTransaction.objects
        .filter(idempotency_key=idempotency_key)
        .first()
    )

    if existing_transaction:
        if (
            existing_transaction.transaction_type
            != LeaveBalanceTransaction.TransactionType.EXPIRY
            or existing_transaction.balance_id != balance.pk
            or existing_transaction.days >= ZERO_DAYS
        ):
            raise ValidationError(
                "The existing expiry transaction does not match "
                "this carry-forward lot."
            )

        if lot.remaining_days != ZERO_DAYS:
            raise ValidationError(
                "An expiry transaction already exists, but the "
                "carry-forward lot still has remaining days. "
                "Manual reconciliation is required."
            )

        return {
            "status": "already_expired",
            "lot_id": lot.pk,
            "expired_days": abs(existing_transaction.days),
        }

    remaining_days = lot.remaining_days

    if remaining_days < ZERO_DAYS:
        raise ValidationError(
            "Carry-forward lot cannot have negative remaining days."
        )

    if remaining_days == ZERO_DAYS:
        return {
            "status": "no_remaining_days",
            "lot_id": lot.pk,
            "expired_days": ZERO_DAYS,
        }

    if balance.entitled_days < remaining_days:
        raise ValidationError(
            "Balance entitlement is smaller than the remaining "
            "carry-forward amount. Expiry was not processed."
        )

    LeaveBalanceTransaction.objects.create(
        organization_id=balance.organization_id,
        employee_id=balance.employee_id,
        leave_type_id=balance.leave_type_id,
        balance=balance,
        transaction_type=LeaveBalanceTransaction.TransactionType.EXPIRY,
        days=-remaining_days,
        effective_date=lot.expires_on,
        policy_version=lot.policy_version,
        policy_rule=lot.policy_rule,
        idempotency_key=idempotency_key,
        description=(
            f"Expired unused carry-forward leave from lot {lot.pk}."
        ),
    )

    balance.entitled_days -= remaining_days
    balance.save(update_fields=["entitled_days"])

    lot.remaining_days = ZERO_DAYS
    lot.save(
        update_fields=[
            "remaining_days",
            "updated_at",
        ]
    )

    return {
        "status": "expired",
        "lot_id": lot.pk,
        "expired_days": remaining_days,
    }
