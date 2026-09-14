import re

from django.db import transaction

from .models import (
    EmployeeIDSequence,
    OnboardingReferenceSequence,
    Employee,
    EmployeeIDConfiguration,
    OnboardingCorrectionRequest,
    OnboardingCorrectionItem,
)


@transaction.atomic
def get_next_employee_id_sequence():
    sequence, created = EmployeeIDSequence.objects.select_for_update().get_or_create(
        id=1,
        defaults={"last_number": 0}
    )

    sequence.last_number += 1
    sequence.save(update_fields=["last_number", "updated_at"])

    return sequence.last_number



@transaction.atomic
def get_next_onboarding_reference():
    sequence, created = OnboardingReferenceSequence.objects.select_for_update().get_or_create(
        id=1,
        defaults={"last_number": 0}
    )

    sequence.last_number += 1
    sequence.save(update_fields=["last_number", "updated_at"])

    return f"ONB-{sequence.last_number:06d}"



SUPPORTED_PLACEHOLDERS = {
    "{COMPANY}",
    "{STATE}",
    "{CITY}",
    "{BRANCH}",
    "{YEAR}",
    "{MONTH}",
    "{DEPARTMENT}",
    "{SEQUENCE}",
}



def validate_employee_id_pattern(pattern):
    placeholders = set(
        re.findall(r"\{[^{}]+\}", pattern)
    )

    unsupported = placeholders - SUPPORTED_PLACEHOLDERS

    if unsupported:
        raise ValueError(
            "Unsupported Employee ID placeholder(s): "
            + ", ".join(sorted(unsupported))
        )

    if "{COMPANY}" not in placeholders:
        raise ValueError(
            "Employee ID pattern must contain {COMPANY}."
        )

    if "{SEQUENCE}" not in placeholders:
        raise ValueError(
            "Employee ID pattern must contain {SEQUENCE}."
        )

    return True



def get_active_employee_id_configuration():
    return (
        EmployeeIDConfiguration.objects
        .filter(is_active=True)
        .order_by("-updated_at")
        .first()
    )



def build_employee_id(employee, sequence_number):
    configuration = get_active_employee_id_configuration()

    if configuration is None:
        raise ValueError(
            "No active Employee ID configuration has been configured."
        )

    pattern = configuration.pattern

    replacements = {
        "{COMPANY}": "WS",
        "{STATE}": employee.branch.state,
        "{CITY}": employee.branch.city,
        "{BRANCH}": employee.branch.code,
        "{YEAR}": str(employee.joining_date.year),
        "{MONTH}": f"{employee.joining_date.month:02d}",
        "{DEPARTMENT}": employee.department.code,
        "{SEQUENCE}": f"{sequence_number:03d}",
    }

    for placeholder, value in replacements.items():
        pattern = pattern.replace(
            placeholder,
            value
        )

    return pattern



@transaction.atomic
def generate_employee_id(employee):
    sequence_number = get_next_employee_id_sequence()

    return build_employee_id(
        employee,
        sequence_number
    )


@transaction.atomic
def create_employee(
    *,
    first_name,
    last_name,
    official_email,
    registered_mobile,
    joining_date,
    employee_type,
    department,
    designation,
    branch,
    manager=None,
    probation_end_date=None,
    created_by=None
):
    onboarding_reference = get_next_onboarding_reference()

    employee = Employee(
        first_name=first_name,
        last_name=last_name,
        official_email=official_email,
        registered_mobile=registered_mobile,
        joining_date=joining_date,
        probation_end_date=probation_end_date,
        employee_type=employee_type,
        department=department,
        designation=designation,
        branch=branch,
        manager=manager,
        created_by=created_by,
        updated_by=created_by,
        onboarding_reference=onboarding_reference,
        status=Employee.Status.PENDING_ONBOARDING,
    )

    employee.save()

    return employee



@transaction.atomic
def approve_employee_onboarding(employee, approved_by=None):
    if employee.status != Employee.Status.PENDING_APPROVAL:
        raise ValueError(
            "Employee onboarding is not pending approval."
        )

    configuration = get_active_employee_id_configuration()

    if configuration is None:
        raise ValueError(
            "No active Employee ID configuration has been configured."
        )

    employee.employee_id = generate_employee_id(employee)
    employee.employee_id_configuration = configuration
    employee.status = Employee.Status.ACTIVE
    employee.updated_by = approved_by

    employee.save(
        update_fields=[
            "employee_id",
            "employee_id_configuration",
            "status",
            "updated_by",
            "updated_at",
        ]
    )

    return employee



@transaction.atomic
def create_onboarding_correction_request(
    employee,
    requested_by,
    correction_items,
):
    if employee.status != Employee.Status.ONBOARDING_SUBMITTED:
        raise ValueError(
            "Correction request can only be created for submitted onboarding."
        )

    if not correction_items:
        raise ValueError(
            "At least one correction item is required."
        )

    correction_request = OnboardingCorrectionRequest.objects.create(
        employee=employee,
        requested_by=requested_by,
        status=OnboardingCorrectionRequest.Status.OPEN,
    )

    for item in correction_items:
        OnboardingCorrectionItem.objects.create(
            correction_request=correction_request,
            item_type=item["item_type"],
            field_name=item["field_name"],
            instruction=item["instruction"],
            status=OnboardingCorrectionItem.Status.PENDING,
        )

    employee.status = Employee.Status.CHANGES_REQUIRED
    employee.updated_by = requested_by
    employee.save(
        update_fields=[
            "status",
            "updated_by",
            "updated_at",
        ]
    )

    return correction_request



@transaction.atomic
def start_onboarding_corrections(employee):
    if employee.status != Employee.Status.CHANGES_REQUIRED:
        raise ValueError(
            "Employee is not in a state that requires corrections."
        )

    employee.status = Employee.Status.ONBOARDING_IN_PROGRESS
    employee.save(
        update_fields=[
            "status",
            "updated_at",
        ]
    )

    return employee



@transaction.atomic
def resubmit_onboarding_after_corrections(employee):
    if employee.status != Employee.Status.ONBOARDING_IN_PROGRESS:
        raise ValueError(
            "Employee must be in onboarding progress before resubmission."
        )

    correction_request = (
        OnboardingCorrectionRequest.objects
        .filter(
            employee=employee,
            status=OnboardingCorrectionRequest.Status.OPEN,
        )
        .order_by("-requested_at")
        .first()
    )

    if correction_request is None:
        raise ValueError(
            "No open correction request exists for this employee."
        )

    correction_request.status = (
        OnboardingCorrectionRequest.Status.PENDING_VERIFICATION
    )
    correction_request.save(update_fields=["status"])

    employee.status = Employee.Status.ONBOARDING_SUBMITTED
    employee.save(
        update_fields=[
            "status",
            "updated_at",
        ]
    )

    return correction_request