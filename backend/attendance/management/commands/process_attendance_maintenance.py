from django.core.management.base import BaseCommand

from attendance.services import (
    process_incomplete_checkouts,
    send_forgot_to_apply_wfh_reminders,
    process_missing_attendance_absences,
    archive_old_attendance_records,
)


class Command(BaseCommand):
    help = "Process configured attendance maintenance tasks."

    def handle(self, *args, **options):
        incomplete = process_incomplete_checkouts()
        reminders = send_forgot_to_apply_wfh_reminders()
        absences = process_missing_attendance_absences()
        archived = archive_old_attendance_records()

        self.stdout.write(
            self.style.SUCCESS(
                f"Incomplete checkout records processed: {incomplete}"
            )
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"WFH reminder records created: {reminders}"
            )
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"Missing-attendance absences marked: {absences}"
            )
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"Attendance records archived: {archived}"
            )
        )