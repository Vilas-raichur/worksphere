from rest_framework import serializers
from django.contrib.auth.password_validation import validate_password
from .models import (
    Employee,
    OnboardingCorrectionItem,
    OnboardingCorrectionRequest,
    EmployeeOnboardingDetails,
    EmployeeDocument,
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
            Employee.objects.get(
                onboarding_reference=value
            )
        except Employee.DoesNotExist:
            raise serializers.ValidationError(
                "Employee with this onboarding reference does not exist."
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
    onboarding_reference = serializers.CharField(
        max_length=20,
        required=False,
    )

    def validate(self, attrs):
        request = self.context.get("request")

        if request is None or not request.user.is_authenticated:
            raise serializers.ValidationError(
                "Authentication is required."
            )

        try:
            employee = request.user.employee_record
        except Employee.DoesNotExist:
            raise serializers.ValidationError(
                "The authenticated user is not linked to an employee record."
            )

        onboarding_reference = attrs.get(
            "onboarding_reference"
        )

        if (
            onboarding_reference
            and onboarding_reference
            != employee.onboarding_reference
        ):
            raise serializers.ValidationError(
                {
                    "onboarding_reference": (
                        "The onboarding reference does not belong "
                        "to the authenticated employee."
                    )
                }
            )

        attrs["employee"] = employee

        return attrs



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

        request = self.context.get("request")

        if (
            request is None
            or not request.user.is_authenticated
            or employee.user_id != request.user.id
        ):
            raise serializers.ValidationError(
                "The onboarding reference does not belong to the authenticated employee."
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

        request = self.context.get("request")

        if (
            request is None
            or not request.user.is_authenticated
            or employee.user_id != request.user.id
        ):
            raise serializers.ValidationError(
                "The onboarding reference does not belong to the authenticated employee."
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


class EmployeeDocumentVerificationSerializer(serializers.Serializer):
    document_id = serializers.IntegerField()


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


class EmployeeOnboardingDetailsSerializer(
    serializers.ModelSerializer
):
    class Meta:
        model = EmployeeOnboardingDetails
        fields = (
            "address_line_1",
            "address_line_2",
            "city",
            "state",
            "postal_code",
            "blood_group",
            "emergency_contact_name",
            "emergency_contact_mobile",
            "emergency_contact_relationship",
            "created_at",
            "updated_at",
        )
        read_only_fields = (
            "created_at",
            "updated_at",
        )


class EmployeeOnboardingDetailsSubmissionSerializer(
    serializers.Serializer
):
    address_line_1 = serializers.CharField(
        max_length=200,
    )

    city = serializers.CharField(
        max_length=100,
    )

    state = serializers.CharField(
        max_length=100,
    )

    postal_code = serializers.CharField(
        max_length=20,
    )

    blood_group = serializers.CharField(
        max_length=5,
    )

    emergency_contact_name = serializers.CharField(
        max_length=150,
    )

    emergency_contact_mobile = serializers.CharField(
        max_length=15,
    )

    emergency_contact_relationship = serializers.CharField(
        max_length=50,
    )


class EmployeeDocumentUploadSerializer(serializers.Serializer):
    document_requirement_id = serializers.IntegerField()

    file = serializers.FileField()


class VerifyEmployeeActivationTokenSerializer(serializers.Serializer):
    activation_token = serializers.CharField(
        max_length=200
    )


class ResendEmployeeActivationSerializer(serializers.Serializer):
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
                "Activation link can only be resent before onboarding activation."
            )

        if employee.user_id is None:
            raise serializers.ValidationError(
                "Employee account does not exist."
            )

        if employee.user.is_active:
            raise serializers.ValidationError(
                "Employee account is already active."
            )

        return value


class RequestEmployeeActivationOTPSerializer(serializers.Serializer):
    activation_token = serializers.CharField(
        max_length=200
    )

    onboarding_reference = serializers.CharField(
        max_length=20
    )


class VerifyEmployeeActivationOTPSerializer(serializers.Serializer):
    activation_token = serializers.CharField(
        max_length=200
    )

    onboarding_reference = serializers.CharField(
        max_length=20
    )

    otp_code = serializers.RegexField(
        regex=r"^\d{6}$",
        error_messages={
            "invalid": "OTP must be exactly 6 digits."
        }
    )


class SetEmployeeActivationPasswordSerializer(
    serializers.Serializer
):
    activation_token = serializers.CharField(
        max_length=200,
        write_only=True,
    )

    onboarding_reference = serializers.CharField(
        max_length=20,
        write_only=True,
    )

    password = serializers.CharField(
        write_only=True,
        trim_whitespace=False,
    )

    password_confirmation = serializers.CharField(
        write_only=True,
        trim_whitespace=False,
    )

    def validate(self, attrs):
        password = attrs["password"]
        password_confirmation = attrs["password_confirmation"]

        if password != password_confirmation:
            raise serializers.ValidationError(
                {
                    "password_confirmation": (
                        "Passwords do not match."
                    )
                }
            )

        validate_password(password)

        return attrs


class ResolveOnboardingCorrectionItemSerializer(serializers.Serializer):
    correction_item_id = serializers.IntegerField()

    def validate_correction_item_id(self, value):
        try:
            OnboardingCorrectionItem.objects.get(
                id=value
            )
        except OnboardingCorrectionItem.DoesNotExist:
            raise serializers.ValidationError(
                "Correction item does not exist."
            )

        return value