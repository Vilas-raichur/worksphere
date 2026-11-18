from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from django.utils.dateparse import parse_date

from employees.models import Employee
from leave_management.carry_forward_generation_services import (
    generate_carry_forward_lots,
)


class Command(BaseCommand):
    help = (
        "Generate completed leave carry-forward lots "
        "for active employees."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--date",
            type=str,
            help="Processing date in YYYY-MM-DD format.",
        )

        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Preview generation without saving database changes.",
        )

    def handle(self, *args, **options):
        raw_date = options.get("date")

        if raw_date:
            processing_date = parse_date(raw_date)

            if processing_date is None:
                raise CommandError(
                    "Invalid date. Use YYYY-MM-DD."
                )
        else:
            processing_date = timezone.localdate()

        dry_run = options["dry_run"]

        employees = Employee.objects.filter(
            organization__isnull=False,
            status=Employee.Status.ACTIVE,
        ).order_by("organization_id", "id")

        employee_count = employees.count()
        total_created = 0
        total_skipped = 0
        total_failed = 0
        total_planned = 0

        self.stdout.write(
            f"Processing date: {processing_date}"
        )
        self.stdout.write(
            f"Active employees found: {employee_count}"
        )

        if dry_run:
            self.stdout.write(
                self.style.WARNING(
                    "DRY RUN: database changes will be rolled back."
                )
            )

        for employee in employees.iterator():
            try:
                result = generate_carry_forward_lots(
                    employee=employee,
                    processing_date=processing_date,
                    dry_run=dry_run,
                )

                total_created += result["created"]
                total_skipped += result["skipped"]
                total_failed += result["failed"]

                planned = sum(
                    1
                    for item in result["results"]
                    if item["status"] == "dry_run"
                )
                total_planned += planned

                for item in result["results"]:
                    if item["status"] == "failed":
                        self.stderr.write(
                            self.style.ERROR(
                                f"Employee {employee.pk}: "
                                f"{item['error']}"
                            )
                        )

            except Exception as exc:
                total_failed += 1
                self.stderr.write(
                    self.style.ERROR(
                        f"Employee {employee.pk} failed: {exc}"
                    )
                )

        self.stdout.write("")
        self.stdout.write("Carry-forward generation summary")
        self.stdout.write(
            f"Employees processed: {employee_count}"
        )

        if dry_run:
            self.stdout.write(
                f"Lots that would be created: {total_planned}"
            )
        else:
            self.stdout.write(
                f"Lots created: {total_created}"
            )

        self.stdout.write(
            f"Already generated / skipped: {total_skipped}"
        )
        self.stdout.write(f"Failures: {total_failed}")

        if total_failed:
            raise CommandError(
                "Carry-forward generation completed with failures. "
                "Review the errors above."
            )

        self.stdout.write(
            self.style.SUCCESS(
                "Carry-forward generation completed successfully."
            )
        )