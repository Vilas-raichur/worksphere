from django.db import models
from django.conf import settings
from django.db.models import Q


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

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    updated_at = models.DateTimeField(
        auto_now=True
    )

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