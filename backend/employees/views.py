from rest_framework import status
from rest_framework.permissions import IsAuthenticated

from .models import (
    Employee,
    EmployeeDocument,
    OnboardingCorrectionRequest,
    OnboardingCorrectionItem,
)

from rest_framework.response import Response
from rest_framework.views import APIView
from accounts.models import DocumentRequirement
from rest_framework.parsers import MultiPartParser, FormParser
from rest_framework.generics import GenericAPIView

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
    VerifyEmployeeActivationTokenSerializer,
    ResendEmployeeActivationSerializer,
    RequestEmployeeActivationOTPSerializer,
    VerifyEmployeeActivationOTPSerializer,
    SetEmployeeActivationPasswordSerializer,
    EmployeeOnboardingDetailsSerializer,
    EmployeeOnboardingDetailsSubmissionSerializer,
    EmployeeDocumentUploadSerializer,
    EmployeeDocumentVerificationSerializer,
)

from .services import (
    start_employee_onboarding,
    submit_employee_onboarding,
    start_onboarding_corrections,
    resubmit_onboarding_after_corrections,
    verify_onboarding_correction_request,
    resolve_onboarding_correction_item,
    approve_employee_onboarding,
    get_valid_employee_activation_token,
    resend_employee_activation_notification,
    create_employee_activation_otp,
    verify_employee_activation_otp,
    set_employee_activation_password,
    save_employee_onboarding_details,
    validate_employee_onboarding_details_for_submission,
    save_employee_document,
    can_approve_employee_onboarding,
    can_manage_onboarding_corrections,
    verify_employee_document,
)

from rest_framework.parsers import (
    FormParser,
    MultiPartParser,
)


def mask_email(email):
    local_part, domain = email.split("@", 1)

    if len(local_part) <= 1:
        masked_local = "*"
    elif len(local_part) <= 4:
        masked_local = local_part[0] + "***"
    else:
        masked_local = local_part[:4] + "***"

    return f"{masked_local}@{domain}"


class EmployeeOnboardingDocumentsAPIView(GenericAPIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [
        MultiPartParser,
        FormParser,
    ]
    serializer_class = EmployeeDocumentUploadSerializer

    def get(self, request):
        try:
            employee = request.user.employee_record
        except Employee.DoesNotExist:
            return Response(
                {
                    "error": (
                        "The authenticated user is not linked "
                        "to an employee record."
                    ),
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        requirements = (
            DocumentRequirement.objects
            .filter(
                organization_id=employee.organization_id,
                is_active=True,
            )
            .order_by("name")
        )

        documents = {
            document.document_requirement_id: document
            for document in employee.documents.all()
        }

        response_data = []

        for requirement in requirements:
            document = documents.get(requirement.id)

            file_url = None

            if document is not None and document.file:
                file_url = request.build_absolute_uri(
                    document.file.url
                )

            response_data.append(
                {
                    "document_requirement_id": requirement.id,
                    "code": requirement.code,
                    "name": requirement.name,
                    "required": requirement.is_required,
                    "uploaded": document is not None,
                    "status": (
                        document.status
                        if document is not None
                        else None
                    ),
                    "file_url": file_url,
                    "remarks": (
                        document.remarks
                        if document is not None
                        else ""
                    ),
                }
            )

        return Response(
            {
                "documents": response_data,
            },
            status=status.HTTP_200_OK,
        )

    def post(self, request):
        try:
            employee = request.user.employee_record
        except Employee.DoesNotExist:
            return Response(
                {
                    "error": (
                        "The authenticated user is not linked "
                        "to an employee record."
                    ),
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        serializer = EmployeeDocumentUploadSerializer(
            data=request.data,
        )

        serializer.is_valid(
            raise_exception=True
        )

        try:
            document = save_employee_document(
                employee=employee,
                document_requirement_id=(
                    serializer.validated_data[
                        "document_requirement_id"
                    ]
                ),
                uploaded_file=serializer.validated_data[
                    "file"
                ],
                uploaded_by=request.user,
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
                "message": (
                    "Employee document uploaded successfully."
                ),
                "document_requirement_id": (
                    document.document_requirement_id
                ),
                "document_name": (
                    document.document_requirement.name
                ),
                "status": document.status,
            },
            status=status.HTTP_200_OK,
        )


class EmployeeOnboardingDetailsAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            employee = request.user.employee_record
        except Employee.DoesNotExist:
            return Response(
                {
                    "error": (
                        "The authenticated user is not linked "
                        "to an employee record."
                    ),
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        onboarding_details, created = (
            EmployeeOnboardingDetails.objects.get_or_create(
                employee=employee
            )
        )

        serializer = EmployeeOnboardingDetailsSerializer(
            onboarding_details
        )

        return Response(
            serializer.data,
            status=status.HTTP_200_OK,
        )

    def patch(self, request):
        try:
            employee = request.user.employee_record
        except Employee.DoesNotExist:
            return Response(
                {
                    "error": (
                        "The authenticated user is not linked "
                        "to an employee record."
                    ),
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        serializer = EmployeeOnboardingDetailsSerializer(
            data=request.data,
            partial=True,
        )

        serializer.is_valid(
            raise_exception=True
        )

        try:
            onboarding_details = (
                save_employee_onboarding_details(
                    employee=employee,
                    details_data=serializer.validated_data,
                )
            )
        except ValueError as exc:
            return Response(
                {
                    "error": str(exc),
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        response_serializer = (
            EmployeeOnboardingDetailsSerializer(
                onboarding_details
            )
        )

        return Response(
            response_serializer.data,
            status=status.HTTP_200_OK,
        )



class EmployeeCreateAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = EmployeeCreateSerializer(
            data=request.data,
            context={"request": request},
        )
        serializer.is_valid(raise_exception=True)

        try:
            employee = serializer.save()
        except ValueError as exc:
            return Response(
                {
                    "error": str(exc),
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(
            {
                "message": "Employee onboarding record created successfully.",
                "onboarding_reference": employee.onboarding_reference,
                "status": employee.status,
                "account_status": "PENDING_ACTIVATION",
            },
            status=status.HTTP_201_CREATED,
        )


class StartOnboardingAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = StartOnboardingSerializer(
            data=request.data,
            context={"request": request},
        )

        serializer.is_valid(
            raise_exception=True
        )

        employee = serializer.validated_data[
            "employee"
        ]

        try:
            employee = start_employee_onboarding(
                employee
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
                "message": (
                    "Employee onboarding started successfully."
                ),
                "onboarding_reference": (
                    employee.onboarding_reference
                ),
                "status": employee.status,
            },
            status=status.HTTP_200_OK,
        )


class SubmitOnboardingAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            employee = request.user.employee_record
        except Employee.DoesNotExist:
            return Response(
                {
                    "error": (
                        "The authenticated user is not linked "
                        "to an employee record."
                    ),
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        try:
            employee = submit_employee_onboarding(
                employee
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
                "message": (
                    "Employee onboarding submitted successfully."
                ),
                "onboarding_reference": (
                    employee.onboarding_reference
                ),
                "status": employee.status,
            },
            status=status.HTTP_200_OK,
        )


class OnboardingCorrectionRequestCreateAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        onboarding_reference = request.data.get("onboarding_reference")

        if onboarding_reference:
            try:
                employee = Employee.objects.get(
                    onboarding_reference=onboarding_reference
                )
            except Employee.DoesNotExist:
                return Response(
                    {
                        "error": "Employee with this onboarding reference does not exist."
                    },
                    status=status.HTTP_404_NOT_FOUND,
                )

            if not can_manage_onboarding_corrections(
                employee,
                request.user,
            ):
                return Response(
                    {
                        "error": (
                            "You are not authorized to create "
                            "onboarding correction requests."
                        )
                    },
                    status=status.HTTP_403_FORBIDDEN,
                )

        serializer = OnboardingCorrectionRequestCreateSerializer(
            data=request.data,
            context={"request": request},
        )

        serializer.is_valid(raise_exception=True)

        try:
            correction_request = serializer.save()
        except PermissionError as exc:
            return Response(
                {
                    "error": str(exc),
                },
                status=status.HTTP_403_FORBIDDEN,
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
                "message": "Onboarding correction request created successfully.",
                "employee": correction_request.employee.onboarding_reference,
                "status": correction_request.status,
                "correction_request_id": correction_request.id,
            },
            status=status.HTTP_201_CREATED,
        )


class StartOnboardingCorrectionsAPIView(APIView):
    permission_classes = [IsAuthenticated]
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
    permission_classes = [IsAuthenticated]
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
    permission_classes = [IsAuthenticated]

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
                correction_item,
                resolved_by=request.user,
            )
        except PermissionError as exc:
            return Response(
                {
                    "error": str(exc),
                },
                status=status.HTTP_403_FORBIDDEN,
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


class VerifyOnboardingCorrectionAPIView(APIView):
    permission_classes = [IsAuthenticated]

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
        except PermissionError as exc:
            return Response(
                {
                    "error": str(exc),
                },
                status=status.HTTP_403_FORBIDDEN,
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


class RequestEmployeeActivationOTPAPIView(APIView):
    authentication_classes = []
    permission_classes = []

    def post(self, request):
        serializer = RequestEmployeeActivationOTPSerializer(
            data=request.data
        )
        serializer.is_valid(raise_exception=True)

        try:
            otp_record = create_employee_activation_otp(
                raw_token=serializer.validated_data[
                    "activation_token"
                ],
                onboarding_reference=serializer.validated_data[
                    "onboarding_reference"
                ],
            )
        except ValueError as exc:
            return Response(
                {
                    "error": str(exc),
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        employee = otp_record.activation_token.employee

        return Response(
            {
                "message": (
                    "Activation OTP has been sent successfully."
                ),
                "otp_status": "SENT",
                "delivery_channel": otp_record.channel,
                "masked_recipient": mask_email(
                    employee.official_email
                ),
                "expires_at": otp_record.expires_at,
            },
            status=status.HTTP_200_OK,
        )


class ResendEmployeeActivationAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = ResendEmployeeActivationSerializer(
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
            resend_employee_activation_notification(
                employee
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
                "message": "Employee activation link resent successfully.",
                "onboarding_reference": employee.onboarding_reference,
                "account_status": "PENDING_ACTIVATION",
            },
            status=status.HTTP_200_OK,
        )


class SetEmployeeActivationPasswordAPIView(APIView):
    authentication_classes = []
    permission_classes = []

    def post(self, request):
        serializer = SetEmployeeActivationPasswordSerializer(
            data=request.data
        )
        serializer.is_valid(raise_exception=True)

        try:
            employee = set_employee_activation_password(
                raw_token=serializer.validated_data[
                    "activation_token"
                ],
                onboarding_reference=serializer.validated_data[
                    "onboarding_reference"
                ],
                password=serializer.validated_data[
                    "password"
                ],
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
                "message": (
                    "Employee account activated successfully."
                ),
                "onboarding_reference": (
                    employee.onboarding_reference
                ),
                "account_status": "ACTIVE",
                "onboarding_status": employee.status,
            },
            status=status.HTTP_200_OK,
        )



class VerifyEmployeeActivationOTPAPIView(APIView):
    authentication_classes = []
    permission_classes = []

    def post(self, request):
        serializer = VerifyEmployeeActivationOTPSerializer(
            data=request.data
        )
        serializer.is_valid(raise_exception=True)

        try:
            otp_record = verify_employee_activation_otp(
                raw_token=serializer.validated_data[
                    "activation_token"
                ],
                onboarding_reference=serializer.validated_data[
                    "onboarding_reference"
                ],
                otp_code=serializer.validated_data[
                    "otp_code"
                ],
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
                "message": (
                    "Activation OTP verified successfully."
                ),
                "otp_status": "VERIFIED",
                "channel": otp_record.channel,
            },
            status=status.HTTP_200_OK,
        )


        
class VerifyEmployeeActivationTokenAPIView(APIView):
    authentication_classes = []
    permission_classes = []

    def post(self, request):
        serializer = VerifyEmployeeActivationTokenSerializer(
            data=request.data
        )
        serializer.is_valid(raise_exception=True)

        try:
            activation_token = get_valid_employee_activation_token(
                serializer.validated_data["activation_token"]
            )
        except ValueError as exc:
            return Response(
                {
                    "error": str(exc),
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        employee = activation_token.employee

        return Response(
            {
                "message": "Activation token is valid.",
                "employee_id": employee.employee_id,
                "employee_name": (
                    f"{employee.first_name} "
                    f"{employee.last_name}"
                ),
                "expires_at": activation_token.expires_at,
            },
            status=status.HTTP_200_OK,
        )



class VerifyEmployeeDocumentAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = EmployeeDocumentVerificationSerializer(
            data=request.data,
            context={"request": request},
        )

        serializer.is_valid(raise_exception=True)

        document_id = serializer.validated_data["document_id"]

        try:
            document = verify_employee_document(
                document_id=document_id,
                verified_by=request.user,
            )
        except PermissionError as exc:
            return Response(
                {
                    "error": str(exc),
                },
                status=status.HTTP_403_FORBIDDEN,
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
                "message": "Employee document verified successfully.",
                "document_id": document.id,
                "onboarding_reference": (
                    document.employee.onboarding_reference
                ),
                "document_requirement_id": (
                    document.document_requirement_id
                ),
                "document_name": (
                    document.document_requirement.name
                ),
                "status": document.status,
            },
            status=status.HTTP_200_OK,
        )



class ApproveOnboardingAPIView(APIView):
    permission_classes = [IsAuthenticated]

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
        except PermissionError as exc:
            return Response(
                {
                    "error": str(exc),
                },
                status=status.HTTP_403_FORBIDDEN,
            )
        except ValueError as exc:
            return Response(
                {
                    "error": str(exc),
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        account_status = "PENDING_ACTIVATION"

        if employee.user_id is not None:
            employee.user.refresh_from_db()
            account_status = (
                "ACTIVE"
                if employee.user.is_active
                else "INACTIVE"
            )

        return Response(
            {
                "message": "Employee onboarding approved successfully.",
                "onboarding_reference": employee.onboarding_reference,
                "employee_id": employee.employee_id,
                "status": employee.status,
                "account_status": account_status,
            },
            status=status.HTTP_200_OK,
        )



