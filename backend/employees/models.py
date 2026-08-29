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

class Employee(models.Model):

    class Status(models.TextChoices):
        PENDING_ONBOARDING = "PENDING_ONBOARDING", "Pending Onboarding"
        ONBOARDING_IN_PROGRESS = "ONBOARDING_IN_PROGRESS", "Onboarding In Progress"
        ONBOARDING_SUBMITTED = "ONBOARDING_SUBMITTED", "Onboarding Submitted"
        CHANGES_REQUIRED = "CHANGES_REQUIRED", "Changes Required"
        PENDING_APPROVAL = "PENDING_APPROVAL", "Pending Approval"
        ACTIVE = "ACTIVE", "Active"
        DEACTIVATED = "DEACTIVATED", "Deactivated"

    employee_id = models.CharField(
        max_length=50,
        unique=True,
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