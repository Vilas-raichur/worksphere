from django.db import models
from django.conf import settings


class Department(models.Model):
    name = models.CharField(
        max_length=100,
        unique=True
    )

    code = models.CharField(
        max_length=20,
        unique=True
    )

    is_active = models.BooleanField(
        default=True
    )

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    updated_at = models.DateTimeField(
        auto_now=True
    )

    def __str__(self):
        return self.name


class Designation(models.Model):
    name = models.CharField(
        max_length=100,
        unique=True
    )

    code = models.CharField(
        max_length=20,
        unique=True
    )

    is_active = models.BooleanField(
        default=True
    )

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    updated_at = models.DateTimeField(
        auto_now=True
    )

    def __str__(self):
        return self.name


class Branch(models.Model):
    name = models.CharField(
        max_length=100,
        unique=True
    )

    code = models.CharField(
        max_length=20,
        unique=True
    )

    state = models.CharField(
        max_length=100
    )

    city = models.CharField(
        max_length=100
    )

    is_active = models.BooleanField(
        default=True
    )

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    updated_at = models.DateTimeField(
        auto_now=True
    )

    def __str__(self):
        return f"{self.name} ({self.code})"

class DepartmentApprover(models.Model):
    organization = models.ForeignKey(
        "accounts.Organization",
        on_delete=models.PROTECT,
        related_name="department_approvers"
    )

    department = models.ForeignKey(
        Department,
        on_delete=models.PROTECT,
        related_name="onboarding_approver_assignments"
    )

    hr_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="onboarding_department_assignments"
    )

    is_active = models.BooleanField(
        default=True
    )

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    updated_at = models.DateTimeField(
        auto_now=True
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "department"],
                name="one_onboarding_approver_per_department"
            )
        ]

    def __str__(self):
        return (
            f"{self.organization.code} - "
            f"{self.department.code} - "
            f"{self.hr_user.username}"
        )


class EmployeeOnboardingDetails(models.Model):
    employee = models.OneToOneField(
        "Employee",
        on_delete=models.CASCADE,
        related_name="onboarding_details",
    )

    address_line_1 = models.CharField(
        max_length=200,
        blank=True,
    )

    address_line_2 = models.CharField(
        max_length=200,
        blank=True,
    )

    city = models.CharField(
        max_length=100,
        blank=True,
    )

    state = models.CharField(
        max_length=100,
        blank=True,
    )

    postal_code = models.CharField(
        max_length=20,
        blank=True,
    )

    blood_group = models.CharField(
        max_length=5,
        blank=True,
    )

    emergency_contact_name = models.CharField(
        max_length=150,
        blank=True,
    )

    emergency_contact_mobile = models.CharField(
        max_length=15,
        blank=True,
    )

    emergency_contact_relationship = models.CharField(
        max_length=50,
        blank=True,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    def __str__(self):
        return (
            f"Onboarding Details - "
            f"{self.employee.onboarding_reference}"
        )


class EmployeeDocument(models.Model):
    class Status(models.TextChoices):
        PENDING_VERIFICATION = (
            "PENDING_VERIFICATION",
            "Pending Verification",
        )
        VERIFIED = "VERIFIED", "Verified"
        CHANGES_REQUIRED = (
            "CHANGES_REQUIRED",
            "Changes Required",
        )

    employee = models.ForeignKey(
        "Employee",
        on_delete=models.CASCADE,
        related_name="documents",
    )

    document_requirement = models.ForeignKey(
        "accounts.DocumentRequirement",
        on_delete=models.PROTECT,
        related_name="employee_documents",
    )

    file = models.FileField(
        upload_to="employee_documents/%Y/%m/",
    )

    status = models.CharField(
        max_length=30,
        choices=Status.choices,
        default=Status.PENDING_VERIFICATION,
    )

    remarks = models.TextField(
        blank=True,
    )

    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="employee_documents_uploaded",
    )

    verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="employee_documents_verified",
    )

    uploaded_at = models.DateTimeField(
        auto_now_add=True,
    )

    verified_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=[
                    "employee",
                    "document_requirement",
                ],
                name="one_current_document_per_requirement",
            )
        ]
        ordering = ["document_requirement__name"]

    def __str__(self):
        return (
            f"{self.employee.onboarding_reference} - "
            f"{self.document_requirement.code} - "
            f"{self.status}"
        )



class Employee(models.Model):

    class Status(models.TextChoices):
        PENDING_ONBOARDING = "PENDING_ONBOARDING", "Pending Onboarding"
        ONBOARDING_IN_PROGRESS = "ONBOARDING_IN_PROGRESS", "Onboarding In Progress"
        ONBOARDING_SUBMITTED = "ONBOARDING_SUBMITTED", "Onboarding Submitted"
        CHANGES_REQUIRED = "CHANGES_REQUIRED", "Changes Required"
        PENDING_APPROVAL = "PENDING_APPROVAL", "Pending Approval"
        REJECTED = "REJECTED", "Rejected"
        ACTIVE = "ACTIVE", "Active"
        DEACTIVATED = "DEACTIVATED", "Deactivated"

    employee_id = models.CharField(
        max_length=50,
        unique=True,
        null=True,
        blank=True
    )

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="employee_record"
    )

    onboarding_reference = models.CharField(
        max_length=20,
        unique=True,
        null=True,
        blank=True
    )

    organization = models.ForeignKey(
    "accounts.Organization",
    on_delete=models.PROTECT,
    related_name="employees",
    null=True,
    blank=True
    )

    first_name = models.CharField(
        max_length=100
    )

    last_name = models.CharField(
        max_length=100
    )

    official_email = models.EmailField(
        unique=True
    )

    registered_mobile = models.CharField(
        max_length=15
    )

    joining_date = models.DateField()

    probation_end_date = models.DateField(
        null=True,
        blank=True
    )

    employee_type = models.CharField(
        max_length=50
    )

    department = models.ForeignKey(
        Department,
        on_delete=models.PROTECT,
        related_name="employees"
    )

    designation = models.ForeignKey(
        Designation,
        on_delete=models.PROTECT,
        related_name="employees"
    )

    branch = models.ForeignKey(
        Branch,
        on_delete=models.PROTECT,
        related_name="employees"
    )

    employee_id_configuration = models.ForeignKey(
        "EmployeeIDConfiguration",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="employees"
    )

    manager = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="team_members"
    )

    status = models.CharField(
        max_length=30,
        choices=Status.choices,
        default=Status.PENDING_ONBOARDING
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="employees_created"
    )

    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="employees_updated"
    )

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    updated_at = models.DateTimeField(
        auto_now=True
    )

    def __str__(self):
        return f"{self.employee_id} - {self.first_name} {self.last_name}"


class EmployeeActivationToken(models.Model):
    employee = models.ForeignKey(
        Employee,
        on_delete=models.CASCADE,
        related_name="activation_tokens"
    )

    token_hash = models.CharField(
        max_length=64,
        unique=True
    )

    expires_at = models.DateTimeField()

    used_at = models.DateTimeField(
        null=True,
        blank=True
    )

    invalidated_at = models.DateTimeField(
        null=True,
        blank=True
    )

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    def __str__(self):
        return (
            f"Activation Token - "
            f"{self.employee.onboarding_reference}"
        )


class EmployeeActivationOTP(models.Model):
    class Channel(models.TextChoices):
        EMAIL = "EMAIL", "Email"
        MOBILE = "MOBILE", "Mobile"

    activation_token = models.ForeignKey(
        EmployeeActivationToken,
        on_delete=models.CASCADE,
        related_name="otp_records",
    )

    channel = models.CharField(
        max_length=20,
        choices=Channel.choices,
        default=Channel.EMAIL,
    )

    code_hash = models.CharField(
        max_length=128
    )

    expires_at = models.DateTimeField()

    attempts = models.PositiveSmallIntegerField(
        default=0
    )

    verified_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    invalidated_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    def __str__(self):
        return (
            f"Activation OTP - "
            f"{self.activation_token.employee.onboarding_reference}"
        )



class OnboardingCorrectionRequest(models.Model):
    class Status(models.TextChoices):
        OPEN = "OPEN", "Open"
        PENDING_VERIFICATION = "PENDING_VERIFICATION", "Pending Verification"
        RESOLVED = "RESOLVED", "Resolved"

    employee = models.ForeignKey(
        Employee,
        on_delete=models.PROTECT,
        related_name="onboarding_correction_requests"
    )

    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="onboarding_correction_requests_created"
    )

    status = models.CharField(
        max_length=30,
        choices=Status.choices,
        default=Status.OPEN
    )

    requested_at = models.DateTimeField(
        auto_now_add=True
    )

    resolved_at = models.DateTimeField(
        null=True,
        blank=True
    )

    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="onboarding_correction_requests_resolved"
    )

    def __str__(self):
        return f"Correction Request - {self.employee}"


class OnboardingCorrectionItem(models.Model):
    class ItemType(models.TextChoices):
        INFORMATION = "INFORMATION", "Information"
        DOCUMENT = "DOCUMENT", "Document"

    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        RESOLVED = "RESOLVED", "Resolved"

    correction_request = models.ForeignKey(
        OnboardingCorrectionRequest,
        on_delete=models.CASCADE,
        related_name="items"
    )

    item_type = models.CharField(
        max_length=20,
        choices=ItemType.choices
    )

    field_name = models.CharField(
        max_length=100
    )

    instruction = models.TextField()

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING
    )

    def __str__(self):
        return f"{self.field_name} - {self.status}"

        

class EmployeeIDConfiguration(models.Model):
    pattern = models.CharField(
        max_length=200
    )

    is_active = models.BooleanField(
        default=True
    )

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    updated_at = models.DateTimeField(
        auto_now=True
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_employee_id_configurations"
    )

    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="updated_employee_id_configurations"
    )

    def clean(self):
        from .services import validate_employee_id_pattern

        validate_employee_id_pattern(self.pattern)

    def __str__(self):
        return self.pattern



class EmployeeIDSequence(models.Model):
    last_number = models.PositiveIntegerField(
        default=0
    )

    updated_at = models.DateTimeField(
        auto_now=True
    )

    def __str__(self):
        return f"Last Employee ID Sequence: {self.last_number}"



class OnboardingReferenceSequence(models.Model):
    last_number = models.PositiveIntegerField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Last Onboarding Reference Sequence: {self.last_number}"