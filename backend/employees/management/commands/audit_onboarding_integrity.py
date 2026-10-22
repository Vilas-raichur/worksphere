from django.core.management.base import BaseCommand

from accounts.models import DocumentRequirement
from employees.models import Employee, EmployeeDocument


class Command(BaseCommand):
    help = (
        "Report employee onboarding/account inconsistencies. "
        "This command does not modify employee records."
    )

    def handle(self, *args, **options):
        employees = (
            Employee.objects
            .select_related("user", "organization")
            .order_by("id")
        )

        organization_ids = (
            employees.values_list("organization_id", flat=True)
            .distinct()
        )

        requirements_by_org = {}

        for organization_id in organization_ids:
            if organization_id is None:
                requirements_by_org[organization_id] = []
                continue

            requirements_by_org[organization_id] = list(
                DocumentRequirement.objects.filter(
                    organization_id=organization_id,
                    is_required=True,
                    is_active=True,
                ).order_by("id")
            )

        issue_count = 0

        for employee in employees:
            issues = []

            if employee.status == Employee.Status.ACTIVE:
                if not (employee.employee_id or "").strip():
                    issues.append("ACTIVE_WITHOUT_PERMANENT_EMPLOYEE_ID")

                if employee.user_id is None:
                    issues.append("ACTIVE_WITHOUT_LINKED_USER")
                elif not employee.user.is_active:
                    issues.append("ACTIVE_WITH_INACTIVE_ACCOUNT")

                requirements = requirements_by_org.get(
                    employee.organization_id,
                    [],
                )

                if not requirements:
                    issues.append("NO_ACTIVE_REQUIRED_DOCUMENT_RULES")
                else:
                    documents = {
                        document.document_requirement_id: document
                        for document in EmployeeDocument.objects.filter(
                            employee=employee,
                            document_requirement__organization_id=(
                                employee.organization_id
                            ),
                        )
                    }

                    missing_or_unverified = [
                        requirement.code
                        for requirement in requirements
                        if (
                            requirement.id not in documents
                            or documents[requirement.id].status
                            != EmployeeDocument.Status.VERIFIED
                        )
                    ]

                    if missing_or_unverified:
                        issues.append(
                            "ACTIVE_WITH_MISSING_OR_UNVERIFIED_REQUIRED_DOCUMENTS:"
                            + ",".join(missing_or_unverified)
                        )

            elif employee.employee_id:
                issues.append(
                    "PERMANENT_ID_WHILE_EMPLOYEE_STATUS_IS_NOT_ACTIVE:"
                    + str(employee.status)
                )

            if issues:
                issue_count += 1
                self.stdout.write(
                    self.style.WARNING(
                        f"{employee.onboarding_reference} | "
                        f"employee_id={employee.employee_id!r} | "
                        f"status={employee.status} | "
                        f"issues={' ; '.join(issues)}"
                    )
                )

        if issue_count == 0:
            self.stdout.write(
                self.style.SUCCESS("No potential inconsistencies found.")
            )
        else:
            self.stdout.write(
                self.style.WARNING(
                    f"Potentially inconsistent employee records: {issue_count}"
                )
            )

        self.stdout.write(
            "Read-only audit complete. No employee records were modified."
        )