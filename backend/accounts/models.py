from django.db import models
from django.conf import settings
from django.db.models import Q

import calendar

from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator


class Organization(models.Model):
    name = models.CharField(
        max_length=150,
        unique=True
    )

    code = models.CharField(
        max_length=30,
        unique=True
    )

    activation_link_expiry_hours = models.PositiveIntegerField(
        default=24
    )

    is_active = models.BooleanField(
        default=True
    )

    # Leave type management permissions are configured by Super Admin.
    # Both grants default to disabled.
    allow_admin_manage_leave_types = models.BooleanField(
        default=False
    )
    allow_hr_manage_leave_types = models.BooleanField(
        default=False
    )
    # The organization's leave year starts on this month and day.
    # Examples: 1 January (calendar year), 1 April (financial year).
    leave_year_start_month = models.PositiveSmallIntegerField(
        default=1,
        validators=[
            MinValueValidator(1),
            MaxValueValidator(12),
        ],
    )
    leave_year_start_day = models.PositiveSmallIntegerField(
        default=1,
        validators=[
            MinValueValidator(1),
            MaxValueValidator(31),
        ],
    )
    created_at = models.DateTimeField(
        auto_now_add=True
    )

    updated_at = models.DateTimeField(
        auto_now=True
    )

    def clean(self):
        super().clean()

        month = self.leave_year_start_month
        day = self.leave_year_start_day

        if not 1 <= month <= 12:
            raise ValidationError({
                "leave_year_start_month": "Month must be between 1 and 12."
            })

        if not 1 <= day <= 31:
            raise ValidationError({
                "leave_year_start_day": "Day must be between 1 and 31."
            })

        maximum_day = calendar.monthrange(2000, month)[1]

        if day > maximum_day:
            raise ValidationError({
                "leave_year_start_day": (
                    f"Day {day} is not valid for month {month}."
                )
            })
    def __str__(self):
        return f"{self.name} ({self.code})"


class UserProfile(models.Model):
    class Role(models.TextChoices):
        SUPER_ADMIN = "SUPER_ADMIN", "Super Admin"
        ADMIN = "ADMIN", "Admin"
        HR = "HR", "HR"
        EMPLOYEE = "EMPLOYEE", "Employee"

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="worksphere_profile"
    )

    organization = models.ForeignKey(
        Organization,
        on_delete=models.PROTECT,
        related_name="user_profiles"
    )

    role = models.CharField(
        max_length=30,
        choices=Role.choices
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
                fields=["organization"],
                condition=Q(role="SUPER_ADMIN"),
                name="one_super_admin_per_organization"
            )
        ]

    def __str__(self):
        return f"{self.user.username} - {self.role}"


class OnboardingApprovalPolicy(models.Model):
    organization = models.OneToOneField(
        Organization,
        on_delete=models.CASCADE,
        related_name="onboarding_approval_policy"
    )

    allow_admin_approval = models.BooleanField(
        default=False
    )

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    updated_at = models.DateTimeField(
        auto_now=True
    )

    def __str__(self):
        return (
            f"{self.organization.code} - "
            f"Admin Approval: {self.allow_admin_approval}"
        )


class DocumentRequirement(models.Model):
    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="document_requirements",
    )

    code = models.CharField(
        max_length=50,
    )

    name = models.CharField(
        max_length=150,
    )

    is_required = models.BooleanField(
        default=True,
    )

    is_active = models.BooleanField(
        default=True,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
    )

    updated_at = models.DateTimeField(
        auto_now=True,
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "code"],
                name="unique_document_requirement_code_per_org",
            )
        ]
        ordering = ["name"]

    def __str__(self):
        return (
            f"{self.organization.code} - "
            f"{self.code} - "
            f"{self.name}"
        )