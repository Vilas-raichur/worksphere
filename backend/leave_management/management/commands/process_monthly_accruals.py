from datetime import date

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from django.utils.dateparse import parse_date

from employees.models import Employee
from leave_management.accrual_services import accrue_monthly_leave
from leave_management.policy_selection import select_applicable_leave_rules
from leave_management.leave_periods import get_leave_year_period


class Command(BaseCommand):
    help = (
        "Process monthly leave accruals for active employees "
        "whose published policy rules are due."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--date",
            dest="accrual_date",
            help="Accrual processing date in YYYY-MM-DD format. Defaults to today.",
        )
        parser.add_argument(
            "--period-start",
            required=False,
            help=(
                "Optional balance period start date in YYYY-MM-DD format. "
                "Defaults to the organization's configured leave year."
            ),
        )
        parser.add_argument(
            "--period-end",
            required=False,
            help=(
                "Optional balance period end date in YYYY-MM-DD format. "
                "Defaults to the organization's configured leave year."
            ),
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Preview eligible accruals without saving any transactions.",
        )

    def handle(self, *args, **options):
        accrual_date = self._parse_date(
            options.get("accrual_date") or timezone.localdate().isoformat(),
            "--date",
        )
        period_start_value = options.get("period_start")
        period_end_value = options.get("period_end")

        if bool(period_start_value) != bool(period_end_value):
            raise CommandError(
                "Supply both --period-start and --period-end, or neither."
            )

        period_start_override = None
        period_end_override = None

        if period_start_value and period_end_value:
            period_start_override = self._parse_date(
                period_start_value,
                "--period-start",
            )
            period_end_override = self._parse_date(
                period_end_value,
                "--period-end",
            )

            if period_start_override > period_end_override:
                raise CommandError(
                    "--period-start cannot be after --period-end."
                )

            if not (
                period_start_override
                <= accrual_date
                <= period_end_override
            ):
                raise CommandError(
                    "The accrual date must fall within the supplied "
                    "balance period."
                )

        dry_run = options["dry_run"]

        employees = Employee.objects.filter(
            status=Employee.Status.ACTIVE,
        ).select_related(
            "organization",
            "department",
            "designation",
        ).order_by("id")

        employee_count = employees.count()
        eligible_count = 0
        processed_count = 0
        skipped_count = 0
        failed_count = 0

        period_mode = (
            "Manual override"
            if period_start_override is not None
            else "Organization-configured leave year"
        )

        self.stdout.write(
            f"Accrual date: {accrual_date}\n"
            f"Balance period mode: {period_mode}\n"
            f"Active employees found: {employee_count}\n"
            f"Mode: {'DRY RUN' if dry_run else 'LIVE'}"
        )

        for employee in employees.iterator():
            if period_start_override is not None:
                period_start = period_start_override
                period_end = period_end_override
            else:
                try:
                    period_start, period_end = get_leave_year_period(
                        employee.organization,
                        accrual_date,
                    )
                except Exception as exc:
                    failed_count += 1
                    self.stderr.write(
                        self.style.ERROR(
                            f"Employee {employee.pk}: leave-year resolution "
                            f"failed: {exc}"
                        )
                    )
                    continue

            in_probation = (
                employee.probation_end_date is not None
                and accrual_date <= employee.probation_end_date
            )

            try:
                applicable_rules = select_applicable_leave_rules(
                    organization_id=employee.organization_id,
                    allocation_date=accrual_date,
                    department_id=employee.department_id,
                    designation_id=employee.designation_id,
                    employee_type=employee.employee_type,
                    in_probation=in_probation,
                )
            except Exception as exc:
                failed_count += 1
                self.stderr.write(
                    self.style.ERROR(
                        f"Employee {employee.pk}: policy selection failed: {exc}"
                    )
                )
                continue

            for rule in applicable_rules.values():
                if not self._is_due(rule, accrual_date):
                    skipped_count += 1
                    continue

                eligible_count += 1

                if dry_run:
                    self.stdout.write(
                        self.style.WARNING(
                            f"WOULD PROCESS: employee={employee.pk}, "
                            f"rule={rule.pk}, leave_type={rule.leave_type_id}, "
                            f"days={rule.monthly_accrual_days}"
                        )
                    )
                    continue

                try:
                    transaction = accrue_monthly_leave(
                        employee=employee,
                        rule=rule,
                        accrual_date=accrual_date,
                        period_start=period_start,
                        period_end=period_end,
                    )
                    processed_count += 1

                    self.stdout.write(
                        self.style.SUCCESS(
                            f"Processed: employee={employee.pk}, "
                            f"rule={rule.pk}, transaction={transaction.pk}"
                        )
                    )
                except Exception as exc:
                    failed_count += 1
                    self.stderr.write(
                        self.style.ERROR(
                            f"Employee {employee.pk}, rule {rule.pk}: {exc}"
                        )
                    )

        self.stdout.write("")
        self.stdout.write("Monthly accrual processing summary")
        self.stdout.write(f"Eligible accruals: {eligible_count}")
        self.stdout.write(f"Processed transactions: {processed_count}")
        self.stdout.write(f"Skipped (not due): {skipped_count}")
        self.stdout.write(f"Failures: {failed_count}")

        if dry_run:
            self.stdout.write(
                self.style.WARNING(
                    "DRY RUN completed. No accrual transactions were saved."
                )
            )

        if failed_count:
            raise CommandError(
                f"Processing completed with {failed_count} failure(s). "
                "Review the errors above."
            )

    @staticmethod
    def _parse_date(value, argument_name):
        parsed = parse_date(value)
        if parsed is None:
            raise CommandError(
                f"{argument_name} must be a valid date in YYYY-MM-DD format."
            )
        return parsed

    @staticmethod
    def _is_due(rule, accrual_date):
        if rule.accrual_timing == "MONTH_START":
            return accrual_date.day == 1

        if rule.accrual_timing == "MONTH_END":
            import calendar

            last_day = calendar.monthrange(
                accrual_date.year,
                accrual_date.month,
            )[1]
            return accrual_date.day == last_day

        return False