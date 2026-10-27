from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from employees.models import Employee
from attendance.services import _validate_manager_eligibility

from .models import (
    AttendanceRecord,
    WFHRequest,
    AttendanceException,
)

from attendance.permissions import (
    IsAssignedEligibleAttendanceExceptionManager,
)

from .serializers import (
    AttendanceRecordSerializer,
    AttendanceHistoryQuerySerializer,
    WFHRequestCreateSerializer,
    WFHRequestReviewSerializer,
    WFHRequestRejectSerializer,
    WFHRequestReadSerializer,
    AttendanceExceptionReviewSerializer,
    AttendanceExceptionReadSerializer,
)
from .services import (
    get_employee_for_user,
    local_today,
    check_in_employee,
    check_out_employee,
    get_my_attendance,
    create_wfh_request,
    approve_wfh_request,
    reject_wfh_request,
    resolve_attendance_exception,
)


def _employee_or_response(request):
    try:
        return get_employee_for_user(request.user), None
    except PermissionError as exc:
        return None, Response(
            {"error": str(exc)},
            status=status.HTTP_403_FORBIDDEN,
        )


def _service_error(exc):
    response_status = (
        status.HTTP_403_FORBIDDEN
        if isinstance(exc, PermissionError)
        else status.HTTP_400_BAD_REQUEST
    )
    return Response({"error": str(exc)}, status=response_status)


class AttendanceTodayAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        employee, error_response = _employee_or_response(request)
        if error_response is not None:
            return error_response

        try:
            today = local_today(employee)
        except ValueError as exc:
            return _service_error(exc)

        record = AttendanceRecord.objects.filter(
            employee=employee,
            attendance_date=today,
        ).first()

        return Response(
            {
                "attendance": (
                    AttendanceRecordSerializer(record).data
                    if record else None
                )
            },
            status=status.HTTP_200_OK,
        )


class AttendanceHistoryAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        employee, error_response = _employee_or_response(request)
        if error_response is not None:
            return error_response

        serializer = AttendanceHistoryQuerySerializer(
            data=request.query_params
        )
        serializer.is_valid(raise_exception=True)

        records = get_my_attendance(
            employee,
            start_date=serializer.validated_data.get("start_date"),
            end_date=serializer.validated_data.get("end_date"),
        )

        return Response(
            AttendanceRecordSerializer(records, many=True).data,
            status=status.HTTP_200_OK,
        )


class AttendanceCheckInAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        employee, error_response = _employee_or_response(request)
        if error_response is not None:
            return error_response

        try:
            record = check_in_employee(employee)
        except (ValueError, PermissionError) as exc:
            return _service_error(exc)

        return Response(
            {
                "message": "Attendance check-in completed successfully.",
                "attendance": AttendanceRecordSerializer(record).data,
            },
            status=status.HTTP_201_CREATED,
        )


class AttendanceCheckOutAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        employee, error_response = _employee_or_response(request)
        if error_response is not None:
            return error_response

        try:
            record = check_out_employee(employee)
        except (ValueError, PermissionError) as exc:
            return _service_error(exc)

        return Response(
            {
                "message": "Attendance check-out completed successfully.",
                "attendance": AttendanceRecordSerializer(record).data,
            },
            status=status.HTTP_200_OK,
        )


class WFHRequestListCreateAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        employee, error_response = _employee_or_response(request)
        if error_response is not None:
            return error_response

        requests = WFHRequest.objects.filter(
            employee=employee
        ).order_by("-requested_at")

        return Response(
            WFHRequestReadSerializer(requests, many=True).data,
            status=status.HTTP_200_OK,
        )

    def post(self, request):
        employee, error_response = _employee_or_response(request)
        if error_response is not None:
            return error_response

        serializer = WFHRequestCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            request_obj = create_wfh_request(
                employee=employee,
                **serializer.validated_data,
            )
        except (ValueError, PermissionError) as exc:
            return _service_error(exc)

        return Response(
            {
                "message": "WFH request created successfully.",
                "request": WFHRequestReadSerializer(request_obj).data,
            },
            status=status.HTTP_201_CREATED,
        )


class WFHManagerInboxAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        manager_employee, error_response = _employee_or_response(request)

        if error_response is not None:
            return error_response

        if manager_employee.status != Employee.Status.ACTIVE:
            return Response(
                {"error": "Only active managers may access this inbox."},
                status=status.HTTP_403_FORBIDDEN,
            )

        has_active_reports = Employee.objects.filter(
            organization_id=manager_employee.organization_id,
            manager=manager_employee,
            status=Employee.Status.ACTIVE,
        ).exists()

        pending_requests = WFHRequest.objects.filter(
            manager_at_request=manager_employee,
            status=WFHRequest.Status.PENDING,
        )

        if not has_active_reports and not pending_requests.exists():
            return Response(
                {"error": "Only an assigned manager may access this inbox."},
                status=status.HTTP_403_FORBIDDEN,
            )

        try:
            _validate_manager_eligibility(
                manager_employee,
                manager_employee.organization_id,
            )
        except PermissionError as exc:
            return Response(
                {"error": str(exc)},
                status=status.HTTP_403_FORBIDDEN,
            )

        requests = pending_requests.order_by("requested_at")

        return Response(
            WFHRequestReadSerializer(requests, many=True).data,
            status=status.HTTP_200_OK,
        )


class WFHRequestApproveAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = WFHRequestReviewSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            request_obj = WFHRequest.objects.get(
                id=serializer.validated_data["wfh_request_id"]
            )
        except WFHRequest.DoesNotExist:
            return Response(
                {"error": "WFH request does not exist."},
                status=status.HTTP_404_NOT_FOUND,
            )

        try:
            request_obj = approve_wfh_request(
                request_obj,
                reviewer=request.user,
            )
        except (ValueError, PermissionError) as exc:
            return _service_error(exc)

        return Response(
            {
                "message": "WFH request approved successfully.",
                "request": WFHRequestReadSerializer(request_obj).data,
            },
            status=status.HTTP_200_OK,
        )


class WFHRequestRejectAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = WFHRequestRejectSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            request_obj = WFHRequest.objects.get(
                id=serializer.validated_data["wfh_request_id"]
            )
        except WFHRequest.DoesNotExist:
            return Response(
                {"error": "WFH request does not exist."},
                status=status.HTTP_404_NOT_FOUND,
            )

        try:
            request_obj = reject_wfh_request(
                request_obj,
                reviewer=request.user,
                remarks=serializer.validated_data["remarks"],
            )
        except (ValueError, PermissionError) as exc:
            return _service_error(exc)

        return Response(
            {
                "message": "WFH request rejected successfully.",
                "request": WFHRequestReadSerializer(request_obj).data,
            },
            status=status.HTTP_200_OK,
        )


class AttendanceExceptionManagerInboxAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        manager_employee, error_response = _employee_or_response(request)

        if error_response is not None:
            return error_response

        if manager_employee.status != Employee.Status.ACTIVE:
            return Response(
                {"error": "Only active managers may access this inbox."},
                status=status.HTTP_403_FORBIDDEN,
            )

        has_active_reports = Employee.objects.filter(
            organization_id=manager_employee.organization_id,
            manager=manager_employee,
            status=Employee.Status.ACTIVE,
        ).exists()

        open_exceptions = AttendanceException.objects.filter(
            assigned_manager=manager_employee,
            status=AttendanceException.Status.OPEN,
        )

        if not has_active_reports and not open_exceptions.exists():
            return Response(
                {"error": "Only an assigned manager may access this inbox."},
                status=status.HTTP_403_FORBIDDEN,
            )

        try:
            _validate_manager_eligibility(
                manager_employee,
                manager_employee.organization_id,
            )
        except PermissionError as exc:
            return Response(
                {"error": str(exc)},
                status=status.HTTP_403_FORBIDDEN,
            )

        exceptions = open_exceptions.order_by("detected_at")

        return Response(
            AttendanceExceptionReadSerializer(
                exceptions,
                many=True,
            ).data,
            status=status.HTTP_200_OK,
        )


class AttendanceExceptionResolveAPIView(APIView):
    permission_classes = [
    IsAuthenticated,
    IsAssignedEligibleAttendanceExceptionManager,
    ]

    def post(self, request):
        serializer = AttendanceExceptionReviewSerializer(
            data=request.data
        )
        serializer.is_valid(raise_exception=True)

        try:
            exception_obj = AttendanceException.objects.get(
                id=serializer.validated_data["exception_id"]
            )
        except AttendanceException.DoesNotExist:
            return Response(
                {"error": "Attendance exception does not exist."},
                status=status.HTTP_404_NOT_FOUND,
            )

        try:
            exception_obj = resolve_attendance_exception(
                exception_obj=exception_obj,
                reviewer=request.user,
                resolution=serializer.validated_data["resolution"],
                check_out_at=serializer.validated_data.get("check_out_at"),
                review_notes=serializer.validated_data["review_notes"],
            )
        except (ValueError, PermissionError) as exc:
            return _service_error(exc)

        return Response(
            {
                "message": "Attendance exception resolved successfully.",
                "exception": AttendanceExceptionReadSerializer(
                    exception_obj
                ).data,
            },
            status=status.HTTP_200_OK,
        )