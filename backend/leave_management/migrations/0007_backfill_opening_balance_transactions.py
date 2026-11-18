from decimal import Decimal

from django.db import migrations


def create_opening_balance_transactions(apps, schema_editor):
    LeaveBalance = apps.get_model(
        "leave_management",
        "LeaveBalance",
    )
    LeaveBalanceTransaction = apps.get_model(
        "leave_management",
        "LeaveBalanceTransaction",
    )

    database = schema_editor.connection.alias

    entitlement_transaction_types = [
        "ALLOCATION",
        "ACCRUAL",
        "CARRY_FORWARD",
        "EXPIRY",
        "ADJUSTMENT",
    ]

    balances = (
        LeaveBalance.objects.using(database)
        .all()
        .iterator()
    )

    for balance in balances:
        existing_transactions = (
            LeaveBalanceTransaction.objects.using(database)
            .filter(
                balance_id=balance.pk,
                transaction_type__in=entitlement_transaction_types,
            )
        )

        tracked_days = Decimal("0.00")

        for leave_transaction in existing_transactions.iterator():
            tracked_days += leave_transaction.days

        opening_days = balance.entitled_days - tracked_days

        if opening_days < Decimal("0.00"):
            raise RuntimeError(
                "Cannot backfill opening balance for LeaveBalance "
                f"{balance.pk}: existing entitlement transactions "
                "exceed the recorded entitlement."
            )

        if opening_days == Decimal("0.00"):
            continue

        LeaveBalanceTransaction.objects.using(database).get_or_create(
            idempotency_key=f"opening-balance:{balance.pk}",
            defaults={
                "organization_id": balance.organization_id,
                "employee_id": balance.employee_id,
                "leave_type_id": balance.leave_type_id,
                "balance_id": balance.pk,
                "transaction_type": "ALLOCATION",
                "days": opening_days,
                "effective_date": balance.period_start,
                "description": (
                    "Opening balance migrated from the existing "
                    "leave balance record."
                ),
            },
        )


class Migration(migrations.Migration):

    dependencies = [
        (
            "leave_management",
            "0006_leavebalance_leave_balance_nonnegative_entitlement",
        ),
    ]

    operations = [
        migrations.RunPython(
            create_opening_balance_transactions,
            migrations.RunPython.noop,
        ),
    ]