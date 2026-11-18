from django.contrib import admin

from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone

from .models import (
    Branch,
    Department,
    Designation,
    DepartmentApprover,
    Employee,
    EmployeeOnboardingDetails,
    EmployeeEligibilityHistory,
    EmployeeIDConfiguration,
    EmployeeIDSequence,
    EmployeeActivationToken,
    EmployeeActivationOTP,
    EmployeeDocument,
    OnboardingCorrectionRequest,
    OnboardingCorrectionItem,
    OnboardingReferenceSequence,

)

from .eligibility_services import (
    create_initial_employee_eligibility,
    record_employee_eligibility_change,
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



class EmployeeAdminForm(forms.ModelForm):
    eligibility_effective_from = forms.DateField(
        required=False,
        initial=timezone.localdate,
        widget=forms.DateInput(
            attrs={"type": "date"}
        ),
        help_text=(
            "Date from which the updated eligibility details "
            "will apply."
        ),
    )

    class Meta:
        model = Employee
        fields = "__all__"

    def clean(self):
        cleaned_data = super().clean()

        if not self.instance.pk:
            return cleaned_data

        old_employee = Employee.objects.filter(
            pk=self.instance.pk
        ).first()

        if old_employee is None:
            return cleaned_data

        eligibility_changed = any([
            cleaned_data.get(
                "joining_date",
                old_employee.joining_date,
            ) != old_employee.joining_date,

            cleaned_data.get(
                "probation_end_date",
                old_employee.probation_end_date,
            ) != old_employee.probation_end_date,

            cleaned_data.get(
                "employee_type",
                old_employee.employee_type,
            ) != old_employee.employee_type,

            cleaned_data.get(
                "department",
                old_employee.department,
            ) != old_employee.department,

            cleaned_data.get(
                "designation",
                old_employee.designation,
            ) != old_employee.designation,
        ])

        if not eligibility_changed:
            return cleaned_data

        effective_from = (
            cleaned_data.get("eligibility_effective_from")
            or timezone.localdate()
        )

        latest_history = (
            EmployeeEligibilityHistory.objects.filter(
                employee_id=self.instance.pk
            )
            .order_by("-effective_from", "-pk")
            .first()
        )

        if latest_history is None:
            raise forms.ValidationError(
                "This employee has no eligibility history. "
                "The eligibility change cannot be saved."
            )

        if effective_from <= latest_history.effective_from:
            self.add_error(
                "eligibility_effective_from",
                "The effective date must be later than the "
                "previous eligibility period's start date.",
            )

        return cleaned_data


@admin.register(Employee)
class EmployeeAdmin(admin.ModelAdmin):
    form = EmployeeAdminForm

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

    def save_model(self, request, obj, form, change):
        old_employee = None

        if change:
            old_employee = Employee.objects.get(pk=obj.pk)

        super().save_model(request, obj, form, change)

        if not change:
            create_initial_employee_eligibility(
                employee=obj,
                effective_from=obj.joining_date,
                changed_by=request.user,
            )
            return

        eligibility_fields = (
            "joining_date",
            "probation_end_date",
            "employee_type",
            "department_id",
            "designation_id",
        )

        eligibility_changed = any(
            getattr(old_employee, field)
            != getattr(obj, field)
            for field in eligibility_fields
        )

        if eligibility_changed:
            effective_from = (
                form.cleaned_data.get("eligibility_effective_from")
                or timezone.localdate()
            )

            record_employee_eligibility_change(
                employee=obj,
                effective_from=effective_from,
                changed_by=request.user,
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