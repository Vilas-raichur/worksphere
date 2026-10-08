import hashlib
import re
import secrets
from datetime import timedelta

from pathlib import Path
from django.contrib.auth import get_user_model
from django.contrib.auth.hashers import (
    check_password,
    make_password,
)
from django.db import transaction
from django.utils import timezone
User = get_user_model()
ACTIVATION_OTP_EXPIRY_MINUTES = 10
ACTIVATION_OTP_MAX_ATTEMPTS = 5
ALLOWED_EMPLOYEE_DOCUMENT_EXTENSIONS = {
    ".pdf",
    ".jpg",
    ".jpeg",
    ".png",
}

MAX_EMPLOYEE_DOCUMENT_SIZE = 5 * 1024 * 1024


from .models import (
    EmployeeIDSequence,
    OnboardingReferenceSequence,
    Employee,
    EmployeeDocument,
    EmployeeIDConfiguration,
    OnboardingCorrectionRequest,
    OnboardingCorrectionItem,
    DepartmentApprover,
    EmployeeActivationToken,
    EmployeeActivationOTP,
    EmployeeOnboardingDetails,
    
)

from accounts.models import (
    DocumentRequirement,
    OnboardingApprovalPolicy,
    UserProfile,
)

from notifications.services import (
    send_employee_activation_notification,
    send_employee_activation_otp_notification,
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

    provision_employee_account(employee)

    raw_token, activation_token = create_employee_activation_token(
        employee
    )

    transaction.on_commit(
        lambda: send_employee_activation_notification(
            employee=employee,
            raw_token=raw_token,
        )
    )

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
            "Employee onboarding must be in progress "
            "before submission."
        )

    validate_employee_onboarding_details_for_submission(
        employee
    )

    validate_employee_onboarding_documents_for_submission(
        employee
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



def can_manage_onboarding_corrections(employee, user):
    if user is None or not user.is_authenticated:
        return False

    try:
        user_profile = user.worksphere_profile
    except UserProfile.DoesNotExist:
        return False

    if employee.organization_id != user_profile.organization_id:
        return False

    if user_profile.role != UserProfile.Role.HR:
        return False

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


def can_verify_employee_document(employee, user):
    if user is None or not user.is_authenticated:
        return False

    try:
        user_profile = user.worksphere_profile
    except UserProfile.DoesNotExist:
        return False

    if employee.organization_id != user_profile.organization_id:
        return False

    if user_profile.role != UserProfile.Role.HR:
        return False

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


@transaction.atomic
def verify_employee_document(
    document_id,
    verified_by,
):
    try:
        document = (
            EmployeeDocument.objects
            .select_related("employee", "document_requirement")
            .get(id=document_id)
        )
    except EmployeeDocument.DoesNotExist:
        raise ValueError(
            "Employee document does not exist."
        )

    employee = document.employee

    if not can_verify_employee_document(
        employee,
        verified_by,
    ):
        raise PermissionError(
            "You are not authorized to verify this employee document."
        )

    if document.status == EmployeeDocument.Status.VERIFIED:
        raise ValueError(
            "Employee document is already verified."
        )

    if document.status != EmployeeDocument.Status.PENDING_VERIFICATION:
        raise ValueError(
            "Employee document is not pending verification."
        )

    document.status = EmployeeDocument.Status.VERIFIED
    document.verified_by = verified_by
    document.verified_at = timezone.now()

    document.save(
        update_fields=[
            "status",
            "verified_by",
            "verified_at",
            "updated_at",
        ]
    )

    return document


@transaction.atomic
def provision_employee_account(employee):
    if employee.user_id is not None:
        return employee.user

    if not employee.onboarding_reference:
        raise ValueError(
            "Employee must have an onboarding reference "
            "before an account can be created."
        )

    if employee.organization_id is None:
        raise ValueError(
            "Employee must belong to an organization "
            "before an account can be created."
        )

    if User.objects.filter(
        username=employee.onboarding_reference
    ).exists():
        raise ValueError(
            "A user account with this onboarding reference already exists."
        )

    user = User(
        username=employee.onboarding_reference,
        email=employee.official_email,
        first_name=employee.first_name,
        last_name=employee.last_name,
        is_active=False,
    )

    user.set_unusable_password()
    user.save()

    UserProfile.objects.create(
        user=user,
        organization=employee.organization,
        role=UserProfile.Role.EMPLOYEE,
    )

    employee.user = user
    employee.save(
        update_fields=[
            "user",
            "updated_at",
        ]
    )

    return user

def hash_activation_token(raw_token):
    return hashlib.sha256(
        raw_token.encode("utf-8")
    ).hexdigest()


@transaction.atomic
def create_employee_activation_token(employee):
    if employee.status != Employee.Status.PENDING_ONBOARDING:
        raise ValueError(
            "Activation token can only be created "
            "before onboarding activation."
        )

    if employee.user_id is None:
        raise ValueError(
            "Employee must have an account before "
            "an activation token can be created."
        )

    if employee.user.is_active:
        raise ValueError(
            "Employee account is already active."
        )

    activation_expiry_hours = (
        employee.organization.activation_link_expiry_hours
    )

    EmployeeActivationToken.objects.filter(
        employee=employee,
        used_at__isnull=True,
        invalidated_at__isnull=True,
    ).update(
        invalidated_at=timezone.now()
    )

    raw_token = secrets.token_urlsafe(32)

    activation_token = EmployeeActivationToken.objects.create(
        employee=employee,
        token_hash=hash_activation_token(raw_token),
        expires_at=(
            timezone.now()
            + timedelta(hours=activation_expiry_hours)
        ),
    )

    return raw_token, activation_token


@transaction.atomic
def resend_employee_activation_notification(employee):
    if employee.status != Employee.Status.PENDING_ONBOARDING:
        raise ValueError(
            "Activation link can only be resent before onboarding activation."
        )

    if employee.user_id is None:
        raise ValueError(
            "Employee must have an account before an activation link can be resent."
        )

    if employee.user.is_active:
        raise ValueError(
            "Employee account is already active."
        )

    raw_token, activation_token = create_employee_activation_token(
        employee
    )

    transaction.on_commit(
        lambda: send_employee_activation_notification(
            employee=employee,
            raw_token=raw_token,
        )
    )

    return activation_token



@transaction.atomic
def verify_employee_activation_otp(
    raw_token,
    onboarding_reference,
    otp_code,
):
    activation_token = get_valid_employee_activation_token(
        raw_token
    )

    employee = activation_token.employee

    if employee.onboarding_reference != onboarding_reference:
        raise ValueError(
            "Activation token and onboarding reference do not match."
        )

    otp_record = (
        EmployeeActivationOTP.objects
        .filter(
            activation_token=activation_token,
            channel=EmployeeActivationOTP.Channel.EMAIL,
            verified_at__isnull=True,
            invalidated_at__isnull=True,
        )
        .order_by("-created_at")
        .first()
    )

    if otp_record is None:
        raise ValueError(
            "No active OTP exists for this activation request."
        )

    if otp_record.expires_at <= timezone.now():
        otp_record.invalidated_at = timezone.now()
        otp_record.save(
            update_fields=[
                "invalidated_at",
            ]
        )
        raise ValueError(
            "OTP has expired."
        )

    if otp_record.attempts >= ACTIVATION_OTP_MAX_ATTEMPTS:
        otp_record.invalidated_at = timezone.now()
        otp_record.save(
            update_fields=[
                "invalidated_at",
            ]
        )
        raise ValueError(
            "Maximum OTP attempts exceeded."
        )

    otp_record.attempts += 1

    if not check_password(
        otp_code,
        otp_record.code_hash,
    ):
        if otp_record.attempts >= ACTIVATION_OTP_MAX_ATTEMPTS:
            otp_record.invalidated_at = timezone.now()

        otp_record.save(
            update_fields=[
                "attempts",
                "invalidated_at",
            ]
        )

        raise ValueError(
            "Invalid OTP."
        )

    otp_record.verified_at = timezone.now()

    otp_record.save(
        update_fields=[
            "attempts",
            "verified_at",
        ]
    )

    return otp_record


@transaction.atomic
def create_employee_activation_otp(
    raw_token,
    onboarding_reference,
):
    activation_token = get_valid_employee_activation_token(
        raw_token
    )

    employee = activation_token.employee

    if employee.onboarding_reference != onboarding_reference:
        raise ValueError(
            "Activation token and onboarding reference do not match."
        )

    EmployeeActivationOTP.objects.filter(
        activation_token=activation_token,
        channel=EmployeeActivationOTP.Channel.EMAIL,
        verified_at__isnull=True,
        invalidated_at__isnull=True,
    ).update(
        invalidated_at=timezone.now()
    )

    otp_code = f"{secrets.randbelow(1_000_000):06d}"

    otp_record = EmployeeActivationOTP.objects.create(
        activation_token=activation_token,
        channel=EmployeeActivationOTP.Channel.EMAIL,
        code_hash=make_password(otp_code),
        expires_at=(
            timezone.now()
            + timedelta(minutes=ACTIVATION_OTP_EXPIRY_MINUTES)
        ),
    )

    transaction.on_commit(
        lambda: send_employee_activation_otp_notification(
            employee=employee,
            otp_code=otp_code,
            expires_at=otp_record.expires_at,
        )
    )

    return otp_record


@transaction.atomic
def activate_employee_account(
    raw_token,
    onboarding_reference,
):
    activation_token = get_valid_employee_activation_token(
        raw_token
    )

    employee = activation_token.employee

    if employee.onboarding_reference != onboarding_reference:
        raise ValueError(
            "Activation token and onboarding reference do not match."
        )

    otp_record = (
        EmployeeActivationOTP.objects
        .filter(
            activation_token=activation_token,
            channel=EmployeeActivationOTP.Channel.EMAIL,
            verified_at__isnull=False,
            invalidated_at__isnull=True,
        )
        .order_by("-created_at")
        .first()
    )

    if otp_record is None:
        raise ValueError(
            "Activation OTP must be verified before creating a password."
        )

    if employee.user.is_active:
        raise ValueError(
            "Employee account is already active."
        )

    return employee, activation_token



@transaction.atomic
def set_employee_activation_password(
    raw_token,
    onboarding_reference,
    password,
):
    employee, activation_token = activate_employee_account(
        raw_token=raw_token,
        onboarding_reference=onboarding_reference,
    )

    user = employee.user

    user.set_password(password)
    user.is_active = True
    user.save(
        update_fields=[
            "password",
            "is_active",
        ]
    )

    activation_token.used_at = timezone.now()
    activation_token.save(
        update_fields=[
            "used_at",
        ]
    )

    return employee


@transaction.atomic
def save_employee_document(
    employee,
    document_requirement_id,
    uploaded_file,
    uploaded_by=None,
):
    if employee.user_id is None or not employee.user.is_active:
        raise ValueError(
            "Employee account must be active before uploading documents."
        )

    if employee.status not in (
        Employee.Status.PENDING_ONBOARDING,
        Employee.Status.ONBOARDING_IN_PROGRESS,
        Employee.Status.CHANGES_REQUIRED,
    ):
        raise ValueError(
            "Documents cannot be uploaded in the current onboarding status."
        )

    if uploaded_file is None:
        raise ValueError(
            "A document file is required."
        )

    if uploaded_file.size > 5 * 1024 * 1024:
        raise ValueError(
            "Document file size cannot exceed 5 MB."
        )

    file_name = uploaded_file.name.lower()

    allowed_extensions = (
        ".pdf",
        ".jpg",
        ".jpeg",
        ".png",
    )

    if not file_name.endswith(allowed_extensions):
        raise ValueError(
            "Only PDF, JPG, JPEG, and PNG files are allowed."
        )

    try:
        document_requirement = DocumentRequirement.objects.get(
            id=document_requirement_id,
            organization_id=employee.organization_id,
            is_active=True,
        )
    except DocumentRequirement.DoesNotExist:
        raise ValueError(
            "The selected document requirement does not exist "
            "or is not active for this organization."
        )

    # During a correction cycle, employees may modify only the
    # document requirements explicitly requested by HR.
    active_correction_request = (
        OnboardingCorrectionRequest.objects
        .filter(
            employee=employee,
            status=OnboardingCorrectionRequest.Status.OPEN,
        )
        .order_by("-id")
        .first()
    )

    if active_correction_request is not None:
        pending_document_corrections = (
            OnboardingCorrectionItem.objects
            .filter(
                correction_request=active_correction_request,
                item_type=OnboardingCorrectionItem.ItemType.DOCUMENT,
                status=OnboardingCorrectionItem.Status.PENDING,
            )
            .values_list("field_name", flat=True)
        )

        allowed_document_codes = {
            code.strip().upper()
            for code in pending_document_corrections
            if code
        }

        if document_requirement.code.upper() not in allowed_document_codes:
            raise ValueError(
                "This document is not part of the current onboarding "
                "correction request and cannot be changed."
            )

    existing_document = (
        EmployeeDocument.objects
        .filter(
            employee=employee,
            document_requirement=document_requirement,
        )
        .first()
    )

    if (
        existing_document is not None
        and existing_document.status
        == EmployeeDocument.Status.VERIFIED
    ):
        raise ValueError(
            "A verified document cannot be replaced."
        )

    if uploaded_by is None:
        uploaded_by = employee.user

    if existing_document is None:
        document = EmployeeDocument.objects.create(
            employee=employee,
            document_requirement=document_requirement,
            file=uploaded_file,
            status=EmployeeDocument.Status.PENDING_VERIFICATION,
            uploaded_by=uploaded_by,
        )
    else:
        existing_document.file = uploaded_file
        existing_document.status = (
            EmployeeDocument.Status.PENDING_VERIFICATION
        )
        existing_document.remarks = ""
        existing_document.verified_by = None
        existing_document.verified_at = None
        existing_document.uploaded_by = uploaded_by
        existing_document.save()

        document = existing_document

    return document


@transaction.atomic
def save_employee_onboarding_details(
    employee,
    details_data,
):
    if employee.user_id is None:
        raise ValueError(
            "Employee account does not exist."
        )

    if not employee.user.is_active:
        raise ValueError(
            "Employee account is not active."
        )

    if employee.status not in (
        Employee.Status.PENDING_ONBOARDING,
        Employee.Status.ONBOARDING_IN_PROGRESS,
        Employee.Status.CHANGES_REQUIRED,
    ):
        raise ValueError(
            "Employee onboarding details cannot be updated "
            "from the current status."
        )

    onboarding_details, created = (
        EmployeeOnboardingDetails.objects.get_or_create(
            employee=employee
        )
    )

    for field, value in details_data.items():
        setattr(
            onboarding_details,
            field,
            value,
        )

    onboarding_details.save()

    return onboarding_details


def validate_employee_onboarding_documents_for_submission(
    employee,
):
    required_requirements = DocumentRequirement.objects.filter(
        organization_id=employee.organization_id,
        is_active=True,
        is_required=True,
    )

    missing_documents = []
    changes_required_documents = []

    for requirement in required_requirements:
        document = (
            EmployeeDocument.objects
            .filter(
                employee=employee,
                document_requirement=requirement,
            )
            .first()
        )

        if document is None or not document.file:
            missing_documents.append(
                requirement.name
            )
            continue

        if document.status == (
            EmployeeDocument.Status.CHANGES_REQUIRED
        ):
            changes_required_documents.append(
                requirement.name
            )

    errors = []

    if missing_documents:
        errors.append(
            "Missing required documents: "
            + ", ".join(missing_documents)
        )

    if changes_required_documents:
        errors.append(
            "The following documents require correction: "
            + ", ".join(changes_required_documents)
        )

    if errors:
        raise ValueError(
            " ".join(errors)
        )

    return True



def validate_employee_onboarding_details_for_submission(
    employee,
):
    try:
        onboarding_details = (
            employee.onboarding_details
        )
    except EmployeeOnboardingDetails.DoesNotExist:
        raise ValueError(
            "Employee onboarding details have not been provided."
        )

    required_fields = {
        "address_line_1": "Address",
        "city": "City",
        "state": "State",
        "postal_code": "Postal code",
        "blood_group": "Blood group",
        "emergency_contact_name": "Emergency contact name",
        "emergency_contact_mobile": "Emergency contact mobile",
        "emergency_contact_relationship": (
            "Emergency contact relationship"
        ),
    }

    missing_fields = []

    for field, display_name in required_fields.items():
        value = getattr(
            onboarding_details,
            field,
        )

        if not value or not value.strip():
            missing_fields.append(
                display_name
            )

    if missing_fields:
        raise ValueError(
            "The following required onboarding details "
            "are missing: "
            + ", ".join(missing_fields)
        )

    return onboarding_details


def get_valid_employee_activation_token(raw_token):
    token_hash = hash_activation_token(raw_token)

    activation_token = (
        EmployeeActivationToken.objects
        .select_related("employee", "employee__user")
        .filter(
            token_hash=token_hash,
            used_at__isnull=True,
            invalidated_at__isnull=True,
            expires_at__gt=timezone.now(),
            employee__status=Employee.Status.PENDING_ONBOARDING,
            employee__user__is_active=False,
        )
        .first()
    )

    if activation_token is None:
        raise ValueError(
            "Activation token is invalid or expired."
        )

    return activation_token



@transaction.atomic
def approve_employee_onboarding(
    employee,
    approved_by=None,
):
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

    required_requirements = (
        DocumentRequirement.objects
        .filter(
            organization_id=employee.organization_id,
            is_required=True,
            is_active=True,
        )
        .order_by("id")
    )

    documents = {
        document.document_requirement_id: document
        for document in EmployeeDocument.objects.filter(
            employee=employee,
            document_requirement__organization_id=employee.organization_id,
        )
    }

    unverified_documents = []

    for requirement in required_requirements:
        document = documents.get(requirement.id)

        if (
            document is None
            or document.status != EmployeeDocument.Status.VERIFIED
        ):
            unverified_documents.append(
                requirement.code
            )

    if unverified_documents:
        raise ValueError(
            "All required employee documents must be verified "
            "before final approval. Outstanding documents: "
            + ", ".join(unverified_documents)
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

    provision_employee_account(employee)

    return employee



@transaction.atomic
def create_onboarding_correction_request(
    employee,
    requested_by,
    correction_items,
):
    if not can_manage_onboarding_corrections(
        employee,
        requested_by,
    ):
        raise PermissionError(
            "You are not authorized to create onboarding correction requests."
        )

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
def resolve_onboarding_correction_item(
    correction_item,
    resolved_by,
):
    employee = correction_item.correction_request.employee

    if not can_manage_onboarding_corrections(
        employee,
        resolved_by,
    ):
        raise PermissionError(
            "You are not authorized to resolve onboarding correction items."
        )

    if correction_item.status != OnboardingCorrectionItem.Status.PENDING:
        raise ValueError(
            "Correction item is already resolved."
        )

    if correction_item.correction_request.status != (
        OnboardingCorrectionRequest.Status.PENDING_VERIFICATION
    ):
        raise ValueError(
            "Correction item cannot be resolved because the correction "
            "request is not pending verification."
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
    employee = correction_request.employee

    if not can_manage_onboarding_corrections(
        employee,
        verified_by,
    ):
        raise PermissionError(
            "You are not authorized to verify this onboarding correction request."
        )
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