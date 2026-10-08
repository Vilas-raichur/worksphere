from django.contrib import admin

from .models import (
    Organization,
    UserProfile,
    OnboardingApprovalPolicy,
    DocumentRequirement,
)


@admin.register(Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "code",
        "is_active",
    )


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "organization",
        "role",
    )
    list_filter = (
        "organization",
        "role",
    )


@admin.register(OnboardingApprovalPolicy)
class OnboardingApprovalPolicyAdmin(admin.ModelAdmin):
    list_display = (
        "organization",
        "allow_admin_approval",
    )


@admin.register(DocumentRequirement)
class DocumentRequirementAdmin(admin.ModelAdmin):
    list_display = (
        "organization",
        "code",
        "name",
        "is_required",
        "is_active",
        "created_at",
        "updated_at",
    )

    search_fields = (
        "code",
        "name",
    )

    list_filter = (
        "organization",
        "is_required",
        "is_active",
    )