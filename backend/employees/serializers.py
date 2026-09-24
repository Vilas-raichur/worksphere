from rest_framework import serializers

from .models import Employee
from .services import create_employee


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