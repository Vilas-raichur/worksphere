from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from leave_management.carry_forward_services import (
    expire_carry_forward_lot,
)
from leave_management.models import LeaveCarryForwardLot


class Command(BaseCommand):
    help = "Expire unused carry-forward leave lots."

    def add_arguments(self, parser):
        parser.add_argument(
            "--date",
            type=str,
            help="Processing date in YYYY-MM-DD format. Defaults to today.",
        )

    def handle(self, *args, **options):
        processing_date = timezone.localdate()

        if options["date"]:
            try:
                processing_date = (
                    timezone.datetime.strptime(
                        options["date"],
                        "%Y-%m-%d",
                    ).date()
                )
            except ValueError as exc:
                raise CommandError(
                    "Invalid date. Use YYYY-MM-DD."
                ) from exc

        lot_ids = list(
            LeaveCarryForwardLot.objects.filter(
                expires_on__lte=processing_date,
                remaining_days__gt=0,
            )
            .order_by("expires_on", "id")
            .values_list("id", flat=True)
        )

        processed = 0
        already_expired = 0
        failed = 0
        total_expired_days = 0

        self.stdout.write(
            f"Processing carry-forward expiries for {processing_date}"
        )

        for lot_id in lot_ids:
            try:
                result = expire_carry_forward_lot(
                    lot_id=lot_id,
                    expiry_date=processing_date,
                )

                if result["status"] == "expired":
                    processed += 1
                    total_expired_days += result["expired_days"]

                elif result["status"] == "already_expired":
                    already_expired += 1

            except Exception as exc:
                failed += 1
                self.stderr.write(
                    self.style.ERROR(
                        f"Lot {lot_id}: {exc}"
                    )
                )

        self.stdout.write(
            f"Lots found: {len(lot_ids)}"
        )
        self.stdout.write(
            f"Expired: {processed}"
        )
        self.stdout.write(
            f"Already expired: {already_expired}"
        )
        self.stdout.write(
            f"Failed: {failed}"
        )
        self.stdout.write(
            f"Total days expired: {total_expired_days}"
        )

        if failed:
            raise CommandError(
                f"{failed} carry-forward lot(s) failed."
            )

        self.stdout.write(
            self.style.SUCCESS(
                "Carry-forward expiry processing completed."
            )
        )