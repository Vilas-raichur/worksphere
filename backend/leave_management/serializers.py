from rest_framework import serializers

from leave_management.models import LeaveRequest, LeaveType


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
