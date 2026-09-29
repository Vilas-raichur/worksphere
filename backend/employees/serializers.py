from rest_framework import serializers

from .models import (
    Employee,
    OnboardingCorrectionItem,
    OnboardingCorrectionRequest,
)
from .services import (
    create_employee,
    create_onboarding_correction_request,
)


class EmployeeCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Employee
        fields = [
            "first_name",
            "last_name",
            "official_email",
            "registered_mobile",
            "joining_date",
            "probation_end_date",
            "employee_type",
            "department",
            "designation",
            "branch",
            "manager",
        ]

    def create(self, validated_data):
        request = self.context["request"]

        return create_employee(
            **validated_data,
            created_by=request.user,
        )
from .models import (
    Employee,
    OnboardingCorrectionItem,
)
from .services import (
    create_employee,
    create_onboarding_correction_request,
)


class OnboardingCorrectionItemSerializer(serializers.Serializer):
    item_type = serializers.ChoiceField(
        choices=OnboardingCorrectionItem.ItemType.choices
    )
    field_name = serializers.CharField(max_length=100)
    instruction = serializers.CharField()


class OnboardingCorrectionRequestCreateSerializer(serializers.Serializer):
    onboarding_reference = serializers.CharField(max_length=20)
    correction_items = OnboardingCorrectionItemSerializer(
        many=True
    )

    def validate_onboarding_reference(self, value):
        try:
            employee = Employee.objects.get(
                onboarding_reference=value
            )
        except Employee.DoesNotExist:
            raise serializers.ValidationError(
                "Employee with this onboarding reference does not exist."
            )

        if employee.status != Employee.Status.ONBOARDING_SUBMITTED:
            raise serializers.ValidationError(
                "Correction request can only be created for submitted onboarding."
            )

        return value

    def validate_correction_items(self, value):
        if not value:
            raise serializers.ValidationError(
                "At least one correction item is required."
            )

        return value

    def create(self, validated_data):
        request = self.context["request"]

        employee = Employee.objects.get(
            onboarding_reference=validated_data["onboarding_reference"]
        )

        return create_onboarding_correction_request(
            employee=employee,
            requested_by=request.user,
            correction_items=validated_data["correction_items"],
        )



class StartOnboardingSerializer(serializers.Serializer):
    onboarding_reference = serializers.CharField(max_length=20)

    def validate_onboarding_reference(self, value):
        try:
            employee = Employee.objects.get(
                onboarding_reference=value
            )
        except Employee.DoesNotExist:
            raise serializers.ValidationError(
                "Employee with this onboarding reference does not exist."
            )

        if employee.status != Employee.Status.PENDING_ONBOARDING:
            raise serializers.ValidationError(
                "Employee onboarding cannot be started from the current status."
            )

        return value



class SubmitOnboardingSerializer(serializers.Serializer):
    onboarding_reference = serializers.CharField(max_length=20)

    def validate_onboarding_reference(self, value):
        try:
            employee = Employee.objects.get(
                onboarding_reference=value
            )
        except Employee.DoesNotExist:
            raise serializers.ValidationError(
                "Employee with this onboarding reference does not exist."
            )

        if employee.status != Employee.Status.ONBOARDING_IN_PROGRESS:
            raise serializers.ValidationError(
                "Employee onboarding must be in progress before submission."
            )

        return value



class StartOnboardingCorrectionsSerializer(serializers.Serializer):
    onboarding_reference = serializers.CharField(max_length=20)

    def validate_onboarding_reference(self, value):
        try:
            employee = Employee.objects.get(
                onboarding_reference=value
            )
        except Employee.DoesNotExist:
            raise serializers.ValidationError(
                "Employee with this onboarding reference does not exist."
            )

        if employee.status != Employee.Status.CHANGES_REQUIRED:
            raise serializers.ValidationError(
                "Employee is not in a state that requires corrections."
            )

        return value


class ResubmitOnboardingSerializer(serializers.Serializer):
    onboarding_reference = serializers.CharField(max_length=20)

    def validate_onboarding_reference(self, value):
        try:
            employee = Employee.objects.get(
                onboarding_reference=value
            )
        except Employee.DoesNotExist:
            raise serializers.ValidationError(
                "Employee with this onboarding reference does not exist."
            )

        if employee.status != Employee.Status.ONBOARDING_IN_PROGRESS:
            raise serializers.ValidationError(
                "Employee must be in onboarding progress before resubmission."
            )

        return value


class VerifyOnboardingCorrectionSerializer(serializers.Serializer):
    correction_request_id = serializers.IntegerField()

    def validate_correction_request_id(self, value):
        try:
            correction_request = OnboardingCorrectionRequest.objects.get(
                id=value
            )
        except OnboardingCorrectionRequest.DoesNotExist:
            raise serializers.ValidationError(
                "Correction request does not exist."
            )

        if correction_request.status != (
            OnboardingCorrectionRequest.Status.PENDING_VERIFICATION
        ):
            raise serializers.ValidationError(
                "Correction request is not pending verification."
            )

        return value


class ApproveOnboardingSerializer(serializers.Serializer):
    onboarding_reference = serializers.CharField(max_length=20)

    def validate_onboarding_reference(self, value):
        try:
            employee = Employee.objects.get(
                onboarding_reference=value
            )
        except Employee.DoesNotExist:
            raise serializers.ValidationError(
                "Employee with this onboarding reference does not exist."
            )

        if employee.status != Employee.Status.PENDING_APPROVAL:
            raise serializers.ValidationError(
                "Employee onboarding is not pending approval."
            )

        return value


class ResolveOnboardingCorrectionItemSerializer(serializers.Serializer):
    correction_item_id = serializers.IntegerField()

    def validate_correction_item_id(self, value):
        try:
            correction_item = OnboardingCorrectionItem.objects.get(
                id=value
            )
        except OnboardingCorrectionItem.DoesNotExist:
            raise serializers.ValidationError(
                "Correction item does not exist."
            )

        if correction_item.status != OnboardingCorrectionItem.Status.PENDING:
            raise serializers.ValidationError(
                "Correction item is already resolved."
            )

        if correction_item.correction_request.status != (
            OnboardingCorrectionRequest.Status.PENDING_VERIFICATION
        ):
            raise serializers.ValidationError(
                "Correction item cannot be resolved because the correction "
                "request is not pending verification."
            )

        return value