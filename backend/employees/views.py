from rest_framework import status
from .models import Employee,OnboardingCorrectionRequest,OnboardingCorrectionItem
from rest_framework.response import Response
from rest_framework.views import APIView

from .serializers import (
    EmployeeCreateSerializer,
    OnboardingCorrectionRequestCreateSerializer,
    StartOnboardingSerializer,
    SubmitOnboardingSerializer,
    StartOnboardingCorrectionsSerializer,
    ResubmitOnboardingSerializer,
    VerifyOnboardingCorrectionSerializer,
    ResolveOnboardingCorrectionItemSerializer,
    ApproveOnboardingSerializer,
)
from .services import (
    start_employee_onboarding,
    submit_employee_onboarding,
    start_onboarding_corrections,
    resubmit_onboarding_after_corrections,
    verify_onboarding_correction_request,
    resolve_onboarding_correction_item,
    approve_employee_onboarding,
)

class EmployeeCreateAPIView(APIView):
    def post(self, request):
        serializer = EmployeeCreateSerializer(
            data=request.data,
            context={"request": request},
        )

        serializer.is_valid(raise_exception=True)

        employee = serializer.save()

        return Response(
            {
                "message": "Employee onboarding record created successfully.",
                "onboarding_reference": employee.onboarding_reference,
                "status": employee.status,
            },
            status=status.HTTP_201_CREATED,
        )


class StartOnboardingAPIView(APIView):
    def post(self, request):
        serializer = StartOnboardingSerializer(
            data=request.data,
            context={"request": request},
        )
        serializer.is_valid(raise_exception=True)

        employee = Employee.objects.get(
            onboarding_reference=serializer.validated_data[
                "onboarding_reference"
            ]
        )

        employee = start_employee_onboarding(employee)

        return Response(
            {
                "message": "Employee onboarding started successfully.",
                "onboarding_reference": employee.onboarding_reference,
                "status": employee.status,
            },
            status=status.HTTP_200_OK,
        )


class SubmitOnboardingAPIView(APIView):
    def post(self, request):
        serializer = SubmitOnboardingSerializer(
            data=request.data,
            context={"request": request},
        )
        serializer.is_valid(raise_exception=True)

        employee = Employee.objects.get(
            onboarding_reference=serializer.validated_data[
                "onboarding_reference"
            ]
        )

        employee = submit_employee_onboarding(employee)

        return Response(
            {
                "message": "Employee onboarding submitted successfully.",
                "onboarding_reference": employee.onboarding_reference,
                "status": employee.status,
            },
            status=status.HTTP_200_OK,
        )


class OnboardingCorrectionRequestCreateAPIView(APIView):
    def post(self, request):
        serializer = OnboardingCorrectionRequestCreateSerializer(
            data=request.data,
            context={"request": request},
        )

        serializer.is_valid(raise_exception=True)

        correction_request = serializer.save()

        return Response(
            {
                "message": "Onboarding correction request created successfully.",
                "employee": correction_request.employee.onboarding_reference,
                "status": correction_request.status,
                "correction_request_id": correction_request.id,
            },
            status=status.HTTP_201_CREATED,
        )


class StartOnboardingCorrectionsAPIView(APIView):
    def post(self, request):
        serializer = StartOnboardingCorrectionsSerializer(
            data=request.data,
            context={"request": request},
        )
        serializer.is_valid(raise_exception=True)

        employee = Employee.objects.get(
            onboarding_reference=serializer.validated_data[
                "onboarding_reference"
            ]
        )

        employee = start_onboarding_corrections(employee)

        return Response(
            {
                "message": "Employee correction process started successfully.",
                "onboarding_reference": employee.onboarding_reference,
                "status": employee.status,
            },
            status=status.HTTP_200_OK,
        )


class ResubmitOnboardingAPIView(APIView):
    def post(self, request):
        serializer = ResubmitOnboardingSerializer(
            data=request.data,
            context={"request": request},
        )
        serializer.is_valid(raise_exception=True)

        employee = Employee.objects.get(
            onboarding_reference=serializer.validated_data[
                "onboarding_reference"
            ]
        )

        correction_request = resubmit_onboarding_after_corrections(
            employee
        )

        return Response(
            {
                "message": "Employee onboarding resubmitted successfully.",
                "onboarding_reference": employee.onboarding_reference,
                "status": employee.status,
                "correction_request_status": correction_request.status,
            },
            status=status.HTTP_200_OK,
        )


class ResolveOnboardingCorrectionItemAPIView(APIView):
    def post(self, request):
        serializer = ResolveOnboardingCorrectionItemSerializer(
            data=request.data,
            context={"request": request},
        )
        serializer.is_valid(raise_exception=True)

        correction_item = OnboardingCorrectionItem.objects.get(
            id=serializer.validated_data["correction_item_id"]
        )

        try:
            correction_item = resolve_onboarding_correction_item(
                correction_item
            )
        except ValueError as exc:
            return Response(
                {
                    "error": str(exc),
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(
            {
                "message": "Correction item resolved successfully.",
                "correction_item_id": correction_item.id,
                "status": correction_item.status,
            },
            status=status.HTTP_200_OK,
        )


class ApproveOnboardingAPIView(APIView):
    def post(self, request):
        serializer = ApproveOnboardingSerializer(
            data=request.data,
            context={"request": request},
        )
        serializer.is_valid(raise_exception=True)

        employee = Employee.objects.get(
            onboarding_reference=serializer.validated_data[
                "onboarding_reference"
            ]
        )

        try:
            employee = approve_employee_onboarding(
                employee=employee,
                approved_by=request.user,
            )
        except ValueError as exc:
            return Response(
                {
                    "error": str(exc),
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(
            {
                "message": "Employee onboarding approved successfully.",
                "onboarding_reference": employee.onboarding_reference,
                "employee_id": employee.employee_id,
                "status": employee.status,
            },
            status=status.HTTP_200_OK,
        )


class VerifyOnboardingCorrectionAPIView(APIView):
    def post(self, request):
        serializer = VerifyOnboardingCorrectionSerializer(
            data=request.data,
            context={"request": request},
        )
        serializer.is_valid(raise_exception=True)

        correction_request = OnboardingCorrectionRequest.objects.get(
            id=serializer.validated_data["correction_request_id"]
        )

        try:
            employee = verify_onboarding_correction_request(
                correction_request=correction_request,
                verified_by=request.user,
            )
        except ValueError as exc:
            return Response(
                {
                    "error": str(exc),
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(
            {
                "message": "Onboarding correction request verified successfully.",
                "onboarding_reference": employee.onboarding_reference,
                "employee_status": employee.status,
                "correction_request_status": correction_request.status,
            },
            status=status.HTTP_200_OK,
        )


