import re

from django.db import transaction
from django.utils import timezone

from .models import (
    EmployeeIDSequence,
    OnboardingReferenceSequence,
    Employee,
    EmployeeIDConfiguration,
    OnboardingCorrectionRequest,
    OnboardingCorrectionItem,
    DepartmentApprover,
)

from accounts.models import (
    OnboardingApprovalPolicy,
    UserProfile,
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
    if created_by is None:
        raise ValueError(
            "A WorkSphere user is required to create an employee."
        )

    try:
        user_profile = created_by.worksphere_profile
    except UserProfile.DoesNotExist:
        raise ValueError(
            "The user is not configured as a WorkSphere user."
        )

    if not user_profile.organization.is_active:
        raise ValueError(
            "The user's organization is not active."
        )

    onboarding_reference = get_next_onboarding_reference()

    employee = Employee(
        organization=user_profile.organization,
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
def start_employee_onboarding(employee):
    if employee.status != Employee.Status.PENDING_ONBOARDING:
        raise ValueError(
            "Employee onboarding cannot be started from the current status."
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
def submit_employee_onboarding(employee):
    if employee.status != Employee.Status.ONBOARDING_IN_PROGRESS:
        raise ValueError(
            "Employee onboarding must be in progress before submission."
        )

    employee.status = Employee.Status.ONBOARDING_SUBMITTED
    employee.save(
        update_fields=[
            "status",
            "updated_at",
        ]
    )

    return employee


def can_approve_employee_onboarding(employee, user):
    if user is None or not user.is_authenticated:
        return False

    try:
        user_profile = user.worksphere_profile
    except UserProfile.DoesNotExist:
        return False

    if employee.organization_id != user_profile.organization_id:
        return False

    if user_profile.role == UserProfile.Role.HR:
        assignment = (
            DepartmentApprover.objects
            .filter(
                organization_id=employee.organization_id,
                department_id=employee.department_id,
                hr_user=user,
                is_active=True,
            )
            .first()
        )

        return assignment is not None

    if user_profile.role == UserProfile.Role.ADMIN:
        policy = (
            OnboardingApprovalPolicy.objects
            .filter(
                organization_id=employee.organization_id
            )
            .first()
        )

        return (
            policy is not None
            and policy.allow_admin_approval
        )

    return False


@transaction.atomic
def approve_employee_onboarding(employee, approved_by=None):
    if employee.status != Employee.Status.PENDING_APPROVAL:
        raise ValueError(
            "Employee onboarding is not pending approval."
        )

    if not can_approve_employee_onboarding(
        employee,
        approved_by,
    ):
        raise PermissionError(
            "You are not authorized to approve this employee onboarding."
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


@transaction.atomic
def resolve_onboarding_correction_item(correction_item):
    if correction_item.status != OnboardingCorrectionItem.Status.PENDING:
        raise ValueError(
            "Correction item is already resolved."
        )

    if correction_item.correction_request.status != (
        OnboardingCorrectionRequest.Status.PENDING_VERIFICATION
    ):
        raise ValueError(
            "Correction item cannot be resolved because the correction request "
            "is not pending verification."
        )

    correction_item.status = OnboardingCorrectionItem.Status.RESOLVED
    correction_item.save(
        update_fields=[
            "status",
        ]
    )

    return correction_item


@transaction.atomic
def verify_onboarding_correction_request(
    correction_request,
    verified_by,
):
    if correction_request.status != (
        OnboardingCorrectionRequest.Status.PENDING_VERIFICATION
    ):
        raise ValueError(
            "Correction request is not pending verification."
        )

    pending_items = correction_request.items.filter(
        status=OnboardingCorrectionItem.Status.PENDING
    )

    if pending_items.exists():
        raise ValueError(
            "All correction items must be resolved before onboarding can be approved."
        )

    employee = correction_request.employee

    if employee.status != Employee.Status.ONBOARDING_SUBMITTED:
        raise ValueError(
            "Employee onboarding is not submitted for verification."
        )

    correction_request.status = (
        OnboardingCorrectionRequest.Status.RESOLVED
    )
    correction_request.resolved_by = verified_by
    correction_request.resolved_at = timezone.now()
    correction_request.save(
        update_fields=[
            "status",
            "resolved_by",
            "resolved_at",
        ]
    )

    employee.status = Employee.Status.PENDING_APPROVAL
    employee.updated_by = verified_by
    employee.save(
        update_fields=[
            "status",
            "updated_by",
            "updated_at",
        ]
    )

    return employee