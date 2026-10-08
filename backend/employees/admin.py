from django.contrib import admin

from .models import (
    Department,
    Designation,
    Branch,
    Employee,
    EmployeeOnboardingDetails,
    DepartmentApprover,
    OnboardingCorrectionRequest,
    OnboardingCorrectionItem,
    EmployeeIDConfiguration,
    EmployeeIDSequence,
    OnboardingReferenceSequence,
    EmployeeActivationToken,
    EmployeeActivationOTP,
    EmployeeDocument,
)


@admin.register(Department)
class DepartmentAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "code",
        "is_active",
        "created_at",
        "updated_at",
    )
    search_fields = (
        "name",
        "code",
    )
    list_filter = (
        "is_active",
    )


@admin.register(Designation)
class DesignationAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "code",
        "is_active",
        "created_at",
        "updated_at",
    )
    search_fields = (
        "name",
        "code",
    )
    list_filter = (
        "is_active",
    )


@admin.register(Branch)
class BranchAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "code",
        "state",
        "city",
        "is_active",
        "created_at",
        "updated_at",
    )
    search_fields = (
        "name",
        "code",
        "state",
        "city",
    )
    list_filter = (
        "state",
        "city",
        "is_active",
    )


@admin.register(Employee)
class EmployeeAdmin(admin.ModelAdmin):
    list_display = (
        "employee_id",
        "onboarding_reference",
        "first_name",
        "last_name",
        "department",
        "designation",
        "branch",
        "status",
        "organization",
        "user",
    )
    search_fields = (
        "employee_id",
        "onboarding_reference",
        "first_name",
        "last_name",
        "official_email",
    )
    list_filter = (
        "status",
        "department",
        "designation",
        "branch",
        "organization",
    )
    readonly_fields = (
        "employee_id",
        "onboarding_reference",
        "created_at",
        "updated_at",
    )


@admin.register(EmployeeOnboardingDetails)
class EmployeeOnboardingDetailsAdmin(admin.ModelAdmin):
    list_display = (
        "employee",
        "blood_group",
        "emergency_contact_name",
        "emergency_contact_mobile",
        "emergency_contact_relationship",
        "updated_at",
    )
    search_fields = (
        "employee__onboarding_reference",
        "employee__employee_id",
        "employee__first_name",
        "employee__last_name",
        "emergency_contact_name",
    )


@admin.register(EmployeeDocument)
class EmployeeDocumentAdmin(admin.ModelAdmin):
    list_display = (
        "employee",
        "document_requirement",
        "status",
        "uploaded_by",
        "verified_by",
        "uploaded_at",
        "verified_at",
    )

    search_fields = (
        "employee__onboarding_reference",
        "employee__employee_id",
        "employee__first_name",
        "employee__last_name",
        "document_requirement__code",
        "document_requirement__name",
    )

    list_filter = (
        "status",
        "document_requirement",
    )

    readonly_fields = (
        "uploaded_at",
        "verified_at",
        "updated_at",
    )


@admin.register(DepartmentApprover)
class DepartmentApproverAdmin(admin.ModelAdmin):
    list_display = (
        "organization",
        "department",
        "hr_user",
        "is_active",
        "created_at",
        "updated_at",
    )
    search_fields = (
        "department__name",
        "department__code",
        "hr_user__username",
    )
    list_filter = (
        "organization",
        "department",
        "is_active",
    )


@admin.register(OnboardingCorrectionRequest)
class OnboardingCorrectionRequestAdmin(admin.ModelAdmin):
    list_display = (
        "employee",
        "requested_by",
        "status",
        "requested_at",
        "resolved_at",
        "resolved_by",
    )
    search_fields = (
        "employee__onboarding_reference",
        "employee__employee_id",
        "employee__first_name",
        "employee__last_name",
        "requested_by__username",
    )
    list_filter = (
        "status",
    )


@admin.register(OnboardingCorrectionItem)
class OnboardingCorrectionItemAdmin(admin.ModelAdmin):
    list_display = (
        "correction_request",
        "item_type",
        "field_name",
        "status",
    )
    search_fields = (
        "field_name",
        "instruction",
        "correction_request__employee__onboarding_reference",
    )
    list_filter = (
        "item_type",
        "status",
    )


@admin.register(EmployeeIDConfiguration)
class EmployeeIDConfigurationAdmin(admin.ModelAdmin):
    list_display = (
        "pattern",
        "is_active",
        "created_by",
        "updated_by",
        "created_at",
        "updated_at",
    )
    search_fields = (
        "pattern",
    )
    list_filter = (
        "is_active",
    )


@admin.register(EmployeeIDSequence)
class EmployeeIDSequenceAdmin(admin.ModelAdmin):
    list_display = (
        "last_number",
        "updated_at",
    )


@admin.register(OnboardingReferenceSequence)
class OnboardingReferenceSequenceAdmin(admin.ModelAdmin):
    list_display = (
        "last_number",
        "updated_at",
    )


@admin.register(EmployeeActivationToken)
class EmployeeActivationTokenAdmin(admin.ModelAdmin):
    list_display = (
        "employee",
        "expires_at",
        "used_at",
        "invalidated_at",
        "created_at",
    )
    search_fields = (
        "employee__onboarding_reference",
        "employee__employee_id",
    )
    list_filter = (
        "expires_at",
        "used_at",
        "invalidated_at",
    )
    readonly_fields = (
        "token_hash",
        "created_at",
    )


@admin.register(EmployeeActivationOTP)
class EmployeeActivationOTPAdmin(admin.ModelAdmin):
    list_display = (
        "activation_token",
        "channel",
        "expires_at",
        "attempts",
        "verified_at",
        "invalidated_at",
        "created_at",
    )
    list_filter = (
        "channel",
        "verified_at",
        "invalidated_at",
    )
    readonly_fields = (
        "code_hash",
        "created_at",
    )