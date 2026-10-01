from django.contrib import admin

from .models import (
    Organization,
    UserProfile,
    OnboardingApprovalPolicy,
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