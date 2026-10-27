from rest_framework import serializers

from .models import (
    AttendanceRecord,
    WFHRequest,
    AttendanceException,
)


class AttendanceRecordSerializer(serializers.ModelSerializer):
    class Meta:
        model = AttendanceRecord
        fields = (
            "id",
            "attendance_date",
            "check_in_at",
            "check_out_at",
            "status",
            "source",
            "remarks",
        )


class AttendanceHistoryQuerySerializer(serializers.Serializer):
    start_date = serializers.DateField(required=False)
    end_date = serializers.DateField(required=False)

    def validate(self, attrs):
        start_date = attrs.get("start_date")
        end_date = attrs.get("end_date")

        if (
            start_date is not None
            and end_date is not None
            and end_date < start_date
        ):
            raise serializers.ValidationError(
                "End date cannot be earlier than start date."
            )

        return attrs


class WFHRequestCreateSerializer(serializers.Serializer):
    request_type = serializers.ChoiceField(
        choices=WFHRequest.RequestType.choices
    )
    start_date = serializers.DateField()
    end_date = serializers.DateField()
    reason = serializers.CharField(
        allow_blank=False,
        trim_whitespace=True,
    )

    def validate(self, attrs):
        if attrs["end_date"] < attrs["start_date"]:
            raise serializers.ValidationError(
                "WFH end date cannot be earlier than the start date."
            )

        if not attrs["reason"].strip():
            raise serializers.ValidationError({
                "reason": "A reason is required."
            })

        return attrs


class WFHRequestReviewSerializer(serializers.Serializer):
    wfh_request_id = serializers.IntegerField(min_value=1)


class WFHRequestRejectSerializer(serializers.Serializer):
    wfh_request_id = serializers.IntegerField(min_value=1)
    remarks = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
    )


class WFHRequestReadSerializer(serializers.ModelSerializer):
    class Meta:
        model = WFHRequest
        fields = (
            "id",
            "request_type",
            "start_date",
            "end_date",
            "reason",
            "status",
            "requested_at",
            "manager_at_request",
            "reviewed_by",
            "reviewed_at",
            "review_remarks",
        )


class AttendanceExceptionReviewSerializer(serializers.Serializer):
    exception_id = serializers.IntegerField(min_value=1)
    resolution = serializers.ChoiceField(
        choices=AttendanceException.Resolution.choices
    )
    check_out_at = serializers.DateTimeField(
        required=False,
        allow_null=True,
    )
    review_notes = serializers.CharField(
        required=False,
        allow_blank=True,
        default="",
    )

    def validate(self, attrs):
        if (
            attrs["resolution"]
            == AttendanceException.Resolution.CORRECTED_CHECKOUT
            and attrs.get("check_out_at") is None
        ):
            raise serializers.ValidationError({
                "check_out_at": (
                    "A corrected checkout timestamp is required for "
                    "this resolution."
                )
            })

        return attrs


class AttendanceExceptionReadSerializer(serializers.ModelSerializer):
    class Meta:
        model = AttendanceException
        fields = (
            "id",
            "original_record_id",
            "employee",
            "status",
            "resolution",
            "detected_at",
            "reviewed_at",
            "review_notes",
        )