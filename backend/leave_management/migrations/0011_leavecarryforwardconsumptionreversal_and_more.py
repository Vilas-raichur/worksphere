import django.db.models.deletion
from django.db import migrations, models


def populate_consumption_idempotency_keys(apps, schema_editor):
    Consumption = apps.get_model(
        "leave_management",
        "LeaveCarryForwardConsumption",
    )

    for consumption in Consumption.objects.filter(
        idempotency_key__isnull=True
    ).iterator():
        consumption.idempotency_key = (
            f"carry-forward-consumption:{consumption.pk}"
        )
        consumption.save(update_fields=["idempotency_key"])


class Migration(migrations.Migration):

    dependencies = [
        (
            "leave_management",
            "0010_alter_leavecarryforwardconsumption_options_and_more",
        ),
    ]

    operations = [
        migrations.CreateModel(
            name="LeaveCarryForwardConsumptionReversal",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "reversed_days",
                    models.DecimalField(
                        decimal_places=2,
                        max_digits=6,
                    ),
                ),
                ("reason", models.CharField(max_length=255)),
                (
                    "idempotency_key",
                    models.CharField(max_length=255, unique=True),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "ordering": ["created_at", "id"],
            },
        ),
        migrations.RemoveConstraint(
            model_name="leavecarryforwardconsumption",
            name="unique_carry_forward_request_day",
        ),
        migrations.AddField(
            model_name="leavecarryforwardconsumption",
            name="idempotency_key",
            field=models.CharField(
                blank=True,
                max_length=255,
                null=True,
                unique=True,
            ),
        ),
        migrations.RunPython(
            populate_consumption_idempotency_keys,
            migrations.RunPython.noop,
        ),
        migrations.AlterField(
            model_name="leavecarryforwardconsumption",
            name="idempotency_key",
            field=models.CharField(
                max_length=255,
                unique=True,
            ),
        ),
        migrations.AlterField(
            model_name="leavecarryforwardconsumption",
            name="allocated_days",
            field=models.DecimalField(
                decimal_places=2,
                max_digits=6,
            ),
        ),
        migrations.AlterField(
            model_name="leavecarryforwardconsumption",
            name="consumed_on",
            field=models.DateField(),
        ),
        migrations.AddField(
            model_name="leavecarryforwardconsumptionreversal",
            name="consumption",
            field=models.OneToOneField(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="reversal",
                to="leave_management.leavecarryforwardconsumption",
            ),
        ),
        migrations.RemoveField(
            model_name="leavecarryforwardconsumption",
            name="updated_at",
        ),
        migrations.AddConstraint(
            model_name="leavecarryforwardconsumptionreversal",
            constraint=models.CheckConstraint(
                condition=models.Q(("reversed_days__gt", 0)),
                name="carry_forward_reversal_positive",
            ),
        ),
    ]