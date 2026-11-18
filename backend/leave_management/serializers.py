from rest_framework import serializers

from leave_management.models import (
    LeavePolicy,
    LeavePolicyManagementPermission,
    LeavePolicyRule,
    LeavePolicyVersion,
    LeaveRequest,
    LeaveType,
)


class LeaveTypeReadSerializer(serializers.ModelSerializer):
    class Meta:
        model = LeaveType
        fields = [
            "id",
            "code",
            "name",
            "is_paid",
            "is_active",
        ]
        read_only_fields = fields


class LeaveTypeWriteSerializer(serializers.ModelSerializer):
    class Meta:
        model = LeaveType
        fields = [
            "code",
            "name",
            "is_paid",
            "is_active",
        ]
        extra_kwargs = {
            "is_paid": {"required": False},
            "is_active": {"required": False},
        }

    def validate_code(self, value):
        code = value.strip().upper()

        if not code:
            raise serializers.ValidationError(
                "A leave type code is required."
            )

        organization = self.context.get("organization")

        if organization is None:
            raise serializers.ValidationError(
                "Organization context is required."
            )

        duplicates = LeaveType.objects.filter(
            organization=organization,
            code=code,
        )

        if self.instance is not None:
            duplicates = duplicates.exclude(pk=self.instance.pk)

        if duplicates.exists():
            raise serializers.ValidationError(
                "This leave type code already exists in your organization."
            )

        return code

    def validate_name(self, value):
        name = value.strip()

        if not name:
            raise serializers.ValidationError(
                "A leave type name is required."
            )

        return name


class LeaveRequestCreateSerializer(serializers.Serializer):
    leave_type_id = serializers.IntegerField(min_value=1)
    start_date = serializers.DateField()
    end_date = serializers.DateField()
    reason = serializers.CharField(max_length=5000, trim_whitespace=True)

    def validate(self, attrs):
        if attrs["end_date"] < attrs["start_date"]:
            raise serializers.ValidationError(
                {"end_date": "End date cannot be earlier than start date."}
            )

        if not attrs["reason"]:
            raise serializers.ValidationError(
                {"reason": "A reason is required."}
            )

        return attrs


class LeaveRequestReadSerializer(serializers.ModelSerializer):
    leave_type_code = serializers.CharField(
        source="leave_type.code",
        read_only=True,
    )
    leave_type_name = serializers.CharField(
        source="leave_type.name",
        read_only=True,
    )

    class Meta:
        model = LeaveRequest
        fields = [
            "id",
            "leave_type",
            "leave_type_code",
            "leave_type_name",
            "start_date",
            "end_date",
            "working_days_count",
            "department_id_snapshot",
            "designation_id_snapshot",
            "manager_at_request",
            "reason",
            "status",
            "requested_at",
            "reviewed_by",
            "reviewed_at",
            "review_remarks",
        ]
        read_only_fields = fields


class LeaveDecisionSerializer(serializers.Serializer):
    leave_request_id = serializers.IntegerField(min_value=1)
    decision = serializers.ChoiceField(
        choices=[
            LeaveRequest.Status.APPROVED,
            LeaveRequest.Status.REJECTED,
        ]
    )
    remarks = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=2000,
        default="",
    )



class LeaveTypeManagementPolicySerializer(serializers.Serializer):
    allow_admin_manage_leave_types = serializers.BooleanField(
        required=False
    )
    allow_hr_manage_leave_types = serializers.BooleanField(
        required=False
    )

    def validate(self, attrs):
        if not attrs:
            raise serializers.ValidationError(
                "Provide at least one leave type permission to update."
            )

        return attrs



class LeavePolicyPermissionGrantSerializer(serializers.Serializer):
    admin_profile_id = serializers.IntegerField(min_value=1)


class LeavePolicyPermissionReadSerializer(serializers.ModelSerializer):
    admin_username = serializers.CharField(
        source="admin_user.user.username",
        read_only=True,
    )
    granted_by_username = serializers.CharField(
        source="granted_by.user.username",
        read_only=True,
    )

    class Meta:
        model = LeavePolicyManagementPermission
        fields = [
            "id",
            "admin_user",
            "admin_username",
            "granted_by",
            "granted_by_username",
            "is_active",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields



class LeavePolicyCreateSerializer(serializers.Serializer):
    code = serializers.CharField(max_length=30)
    name = serializers.CharField(max_length=150)
    description = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
    )


class LeavePolicyReadSerializer(serializers.ModelSerializer):
    class Meta:
        model = LeavePolicy
        fields = [
            "id",
            "code",
            "name",
            "description",
            "is_active",
            "created_at",
        ]
        read_only_fields = fields


class LeavePolicyVersionCreateSerializer(serializers.Serializer):
    version_number = serializers.IntegerField(min_value=1)
    effective_from = serializers.DateField()
    effective_until = serializers.DateField(
        required=False,
        allow_null=True,
        default=None,
    )

    def validate(self, attrs):
        end = attrs["effective_until"]
        if end is not None and end < attrs["effective_from"]:
            raise serializers.ValidationError(
                {"effective_until": "Invalid effective date range."}
            )
        return attrs


class LeavePolicyVersionReadSerializer(serializers.ModelSerializer):
    class Meta:
        model = LeavePolicyVersion
        fields = [
            "id",
            "policy",
            "version_number",
            "status",
            "effective_from",
            "effective_until",
            "published_by",
            "published_at",
        ]
        read_only_fields = fields


class LeavePolicyRuleCreateSerializer(serializers.Serializer):
    leave_type_id = serializers.IntegerField(min_value=1)
    monthly_accrual_days = serializers.DecimalField(
        max_digits=6,
        decimal_places=2,
        min_value=0,
    )
    accrual_timing = serializers.ChoiceField(
        choices=LeavePolicyRule.AccrualTiming.choices,
    )
    department_id = serializers.IntegerField(
        min_value=1,
        required=False,
        allow_null=True,
        default=None,
    )
    designation_id = serializers.IntegerField(
        min_value=1,
        required=False,
        allow_null=True,
        default=None,
    )
    employee_type = serializers.CharField(
        required=False,
        allow_blank=True,
        max_length=50,
        default="",
    )
    probation_condition = serializers.ChoiceField(
        choices=LeavePolicyRule.ProbationCondition.choices,
        required=False,
        default=LeavePolicyRule.ProbationCondition.ANY,
    )
    priority = serializers.IntegerField(
        min_value=0,
        required=False,
        default=100,
    )
    allow_carry_forward = serializers.BooleanField(
        required=False,
        default=False,
    )
    carry_forward_limit_days = serializers.DecimalField(
        max_digits=6,
        decimal_places=2,
        min_value=0,
        required=False,
        default=0,
    )
    carry_forward_interval_months = serializers.ChoiceField(
        choices=(1, 2, 3, 4, 6, 12),
        required=False,
        allow_null=True,
        default=None,
    )
    carry_forward_expiry_months = serializers.IntegerField(
        min_value=0,
        max_value=32767,
        required=False,
        allow_null=True,
        default=None,
    )


class LeavePolicyRuleReadSerializer(serializers.ModelSerializer):
    class Meta:
        model = LeavePolicyRule
        fields = [
            "id",
            "version",
            "leave_type",
            "department",
            "designation",
            "employee_type",
            "probation_condition",
            "priority",
            "monthly_accrual_days",
            "accrual_timing",
            "allow_carry_forward",
            "carry_forward_limit_days",
            "carry_forward_interval_months",
            "carry_forward_expiry_months",
            "is_active",
        ]
        read_only_fields = fields
