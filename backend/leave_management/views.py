from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from accounts.models import UserProfile

from attendance.services import (
    _validate_manager_eligibility,
    get_employee_for_user,
)
from employees.models import Employee

from leave_management.models import (
    LeavePolicy,
    LeavePolicyManagementPermission,
    LeavePolicyRule,
    LeavePolicyVersion,
    LeaveRequest,
    LeaveType,
)

from leave_management.serializers import (
    LeaveDecisionSerializer,
    LeaveRequestCreateSerializer,
    LeaveRequestReadSerializer,
    LeaveTypeManagementPolicySerializer,
    LeaveTypeReadSerializer,
    LeaveTypeWriteSerializer,
    LeavePolicyPermissionGrantSerializer,
    LeavePolicyPermissionReadSerializer,
    LeavePolicyCreateSerializer,
    LeavePolicyReadSerializer,
    LeavePolicyVersionCreateSerializer,
    LeavePolicyVersionReadSerializer,
    LeavePolicyRuleCreateSerializer,
    LeavePolicyRuleReadSerializer,
)

from leave_management.services import (
    create_leave_request,
    decide_leave_request,
    cancel_leave_request,
    get_employee_leave_balance_summary,
)

from django.core.exceptions import ValidationError

from leave_management.policy_permissions import (
    grant_leave_policy_permission,
    require_policy_super_admin,
    revoke_leave_policy_permission,
)

from leave_management.policy_configuration import (
    create_leave_policy,
    create_policy_version,
    create_policy_rule,
    publish_policy_version,
    require_policy_manager,
)


def _employee_or_response(request):
    try:
        return get_employee_for_user(request.user), None
    except PermissionError as exc:
        return None, Response(
            {"error": str(exc)},
            status=status.HTTP_403_FORBIDDEN,
        )


def _leave_type_access(request):
    """
    Resolve organization scope and leave-type management permission.
    """
    try:
        profile = request.user.worksphere_profile
    except UserProfile.DoesNotExist:
        profile = None

    if profile is not None:
        organization = profile.organization

        if not organization.is_active:
            return None, False, Response(
                {"error": "The organization is inactive."},
                status=status.HTTP_403_FORBIDDEN,
            )

        if profile.role == UserProfile.Role.SUPER_ADMIN:
            return organization, True, None

        if profile.role == UserProfile.Role.ADMIN:
            return (
                organization,
                organization.allow_admin_manage_leave_types,
                None,
            )

        if profile.role == UserProfile.Role.HR:
            return (
                organization,
                organization.allow_hr_manage_leave_types,
                None,
            )

        if profile.role != UserProfile.Role.EMPLOYEE:
            return None, False, Response(
                {"error": "You are not authorized to access leave types."},
                status=status.HTTP_403_FORBIDDEN,
            )

    try:
        employee = get_employee_for_user(request.user)
    except PermissionError as exc:
        return None, False, Response(
            {"error": str(exc)},
            status=status.HTTP_403_FORBIDDEN,
        )

    if employee.organization_id is None:
        return None, False, Response(
            {"error": "Employee is not assigned to an organization."},
            status=status.HTTP_403_FORBIDDEN,
        )

    if not employee.organization.is_active:
        return None, False, Response(
            {"error": "The organization is inactive."},
            status=status.HTTP_403_FORBIDDEN,
        )

    if (
        profile is not None
        and profile.organization_id != employee.organization_id
    ):
        return None, False, Response(
            {"error": "Your profile and employee organization do not match."},
            status=status.HTTP_403_FORBIDDEN,
        )

    return employee.organization, False, None


class LeaveTypeManagementPolicyAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def _get_super_admin_organization(self, request):
        try:
            profile = request.user.worksphere_profile
        except UserProfile.DoesNotExist:
            profile = None

        if (
            profile is None
            or profile.role != UserProfile.Role.SUPER_ADMIN
        ):
            return None, Response(
                {
                    "error": (
                        "Only the organization's Super Admin may "
                        "configure leave type management permissions."
                    )
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        organization = profile.organization

        if not organization.is_active:
            return None, Response(
                {"error": "The organization is inactive."},
                status=status.HTTP_403_FORBIDDEN,
            )

        return organization, None

    def get(self, request):
        organization, error_response = (
            self._get_super_admin_organization(request)
        )
        if error_response is not None:
            return error_response

        return Response(
            {
                "organization": organization.code,
                "allow_admin_manage_leave_types": (
                    organization.allow_admin_manage_leave_types
                ),
                "allow_hr_manage_leave_types": (
                    organization.allow_hr_manage_leave_types
                ),
            },
            status=status.HTTP_200_OK,
        )

    def patch(self, request):
        organization, error_response = (
            self._get_super_admin_organization(request)
        )
        if error_response is not None:
            return error_response

        serializer = LeaveTypeManagementPolicySerializer(
            data=request.data,
            partial=True,
        )
        serializer.is_valid(raise_exception=True)

        updated_fields = list(serializer.validated_data.keys())

        for field, value in serializer.validated_data.items():
            setattr(organization, field, value)

        organization.save(update_fields=updated_fields + ["updated_at"])

        return Response(
            {
                "message": "Leave type management permissions updated.",
                "organization": organization.code,
                "allow_admin_manage_leave_types": (
                    organization.allow_admin_manage_leave_types
                ),
                "allow_hr_manage_leave_types": (
                    organization.allow_hr_manage_leave_types
                ),
            },
            status=status.HTTP_200_OK,
        )



class LeaveTypeListAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        organization, can_manage, error_response = _leave_type_access(
            request
        )
        if error_response is not None:
            return error_response

        types = LeaveType.objects.filter(
            organization=organization,
        )

        if not can_manage:
            types = types.filter(is_active=True)

        types = types.order_by("name")

        return Response(
            LeaveTypeReadSerializer(types, many=True).data,
            status=status.HTTP_200_OK,
        )

    def post(self, request):
        organization, can_manage, error_response = _leave_type_access(
            request
        )
        if error_response is not None:
            return error_response

        if not can_manage:
            return Response(
                {
                    "error": (
                        "Only HR, Admin, or Super Admin may "
                        "create leave types."
                    )
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        serializer = LeaveTypeWriteSerializer(
            data=request.data,
            context={"organization": organization},
        )
        serializer.is_valid(raise_exception=True)

        leave_type = serializer.save(organization=organization)

        return Response(
            {
                "message": "Leave type created successfully.",
                "leave_type": LeaveTypeReadSerializer(leave_type).data,
            },
            status=status.HTTP_201_CREATED,
        )


class LeaveTypeDetailAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def patch(self, request, leave_type_id):
        organization, can_manage, error_response = _leave_type_access(
            request
        )
        if error_response is not None:
            return error_response

        if not can_manage:
            return Response(
                {
                    "error": (
                        "Only HR, Admin, or Super Admin may "
                        "modify leave types."
                    )
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        leave_type = get_object_or_404(
            LeaveType,
            pk=leave_type_id,
            organization=organization,
        )

        serializer = LeaveTypeWriteSerializer(
            leave_type,
            data=request.data,
            partial=True,
            context={"organization": organization},
        )
        serializer.is_valid(raise_exception=True)

        changed_fields = {
            field: value
            for field, value in serializer.validated_data.items()
            if getattr(leave_type, field) != value
        }

        if not changed_fields:
            return Response(
                {
                    "message": (
                        "No changes were needed. The leave type "
                        "already has the requested values."
                    ),
                    "leave_type": LeaveTypeReadSerializer(
                        leave_type
                    ).data,
                },
                status=status.HTTP_200_OK,
            )

        leave_type = serializer.save()

        return Response(
            {
                "message": "Leave type updated successfully.",
                "leave_type": LeaveTypeReadSerializer(leave_type).data,
            },
            status=status.HTTP_200_OK,
        )



class LeaveRequestListCreateAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        employee, error_response = _employee_or_response(request)
        if error_response is not None:
            return error_response

        requests = (
            LeaveRequest.objects
            .filter(employee=employee)
            .select_related("leave_type")
            .order_by("-requested_at")
        )

        return Response(
            LeaveRequestReadSerializer(requests, many=True).data,
            status=status.HTTP_200_OK,
        )

    def post(self, request):
        employee, error_response = _employee_or_response(request)
        if error_response is not None:
            return error_response

        serializer = LeaveRequestCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        leave_type = get_object_or_404(
            LeaveType,
            pk=serializer.validated_data["leave_type_id"],
            organization_id=employee.organization_id,
            is_active=True,
        )

        try:
            leave_request = create_leave_request(
                employee=employee,
                leave_type=leave_type,
                start_date=serializer.validated_data["start_date"],
                end_date=serializer.validated_data["end_date"],
                reason=serializer.validated_data["reason"],
            )
        except PermissionError as exc:
            return Response(
                {"error": str(exc)},
                status=status.HTTP_403_FORBIDDEN,
            )
        except ValueError as exc:
            return Response(
                {"error": str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(
            {
                "message": "Leave request submitted successfully.",
                "leave_request": LeaveRequestReadSerializer(
                    leave_request
                ).data,
            },
            status=status.HTTP_201_CREATED,
        )


class LeaveManagerInboxAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        manager, error_response = _employee_or_response(request)
        if error_response is not None:
            return error_response

        if manager.status != Employee.Status.ACTIVE:
            return Response(
                {"error": "Only active managers may access this inbox."},
                status=status.HTTP_403_FORBIDDEN,
            )

        has_active_reports = Employee.objects.filter(
            organization_id=manager.organization_id,
            manager=manager,
            status=Employee.Status.ACTIVE,
        ).exists()

        pending_requests = LeaveRequest.objects.filter(
            manager_at_request=manager,
            status=LeaveRequest.Status.PENDING,
        )

        if not has_active_reports and not pending_requests.exists():
            return Response(
                {"error": "Only an assigned manager may access this inbox."},
                status=status.HTTP_403_FORBIDDEN,
            )

        try:
            _validate_manager_eligibility(
                manager,
                manager.organization_id,
            )
        except PermissionError as exc:
            return Response(
                {"error": str(exc)},
                status=status.HTTP_403_FORBIDDEN,
            )

        pending_requests = pending_requests.select_related(
            "employee",
            "leave_type",
        ).order_by("requested_at")

        return Response(
            LeaveRequestReadSerializer(
                pending_requests,
                many=True,
            ).data,
            status=status.HTTP_200_OK,
        )


class LeaveManagerDecisionAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        manager, error_response = _employee_or_response(request)
        if error_response is not None:
            return error_response

        serializer = LeaveDecisionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            leave_request = decide_leave_request(
                leave_request_id=serializer.validated_data[
                    "leave_request_id"
                ],
                reviewer=manager,
                decision=serializer.validated_data["decision"],
                remarks=serializer.validated_data["remarks"],
            )
        except LeaveRequest.DoesNotExist:
            return Response(
                {"error": "Leave request not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
        except PermissionError as exc:
            return Response(
                {"error": str(exc)},
                status=status.HTTP_403_FORBIDDEN,
            )
        except ValueError as exc:
            return Response(
                {"error": str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(
            {
                "message": "Leave request reviewed successfully.",
                "leave_request": LeaveRequestReadSerializer(
                    leave_request
                ).data,
            },
            status=status.HTTP_200_OK,
        )


class LeaveRequestCancelAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, leave_request_id):
        employee, error_response = _employee_or_response(request)

        if error_response is not None:
            return error_response

        try:
            leave_request = cancel_leave_request(
                leave_request_id=leave_request_id,
                employee=employee,
            )
        except LeaveRequest.DoesNotExist:
            return Response(
                {"error": "Leave request not found."},
                status=status.HTTP_404_NOT_FOUND,
            )
        except PermissionError as exc:
            return Response(
                {"error": str(exc)},
                status=status.HTTP_403_FORBIDDEN,
            )
        except ValueError as exc:
            return Response(
                {"error": str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(
            {
                "message": "Leave request cancelled successfully.",
                "leave_request": LeaveRequestReadSerializer(
                    leave_request
                ).data,
            },
            status=status.HTTP_200_OK,
        )


class LeaveBalanceSummaryAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        employee, error_response = _employee_or_response(request)

        if error_response is not None:
            return error_response

        try:
            summary = get_employee_leave_balance_summary(employee)
        except ValueError as exc:
            return Response(
                {"error": str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(
            summary,
            status=status.HTTP_200_OK,
        )



class LeavePolicyPermissionListCreateAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            super_admin = require_policy_super_admin(request.user)
        except PermissionError as exc:
            return Response(
                {"error": str(exc)},
                status=status.HTTP_403_FORBIDDEN,
            )

        permissions = (
            LeavePolicyManagementPermission.objects.filter(
                organization_id=super_admin.organization_id,
            )
            .select_related("admin_user__user", "granted_by__user")
            .order_by("id")
        )

        serializer = LeavePolicyPermissionReadSerializer(
            permissions,
            many=True,
        )
        return Response(serializer.data)

    def post(self, request):
        serializer = LeavePolicyPermissionGrantSerializer(
            data=request.data
        )
        serializer.is_valid(raise_exception=True)

        try:
            permission = grant_leave_policy_permission(
                granted_by=request.user,
                admin_profile_id=(
                    serializer.validated_data["admin_profile_id"]
                ),
            )
        except PermissionError as exc:
            return Response(
                {"error": str(exc)},
                status=status.HTTP_403_FORBIDDEN,
            )
        except ValidationError as exc:
            return Response(
                {"error": exc.message_dict},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(
            LeavePolicyPermissionReadSerializer(permission).data,
            status=status.HTTP_200_OK,
        )


class LeavePolicyPermissionRevokeAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def delete(self, request, permission_id):
        try:
            permission = revoke_leave_policy_permission(
                revoked_by=request.user,
                permission_id=permission_id,
            )
        except PermissionError as exc:
            return Response(
                {"error": str(exc)},
                status=status.HTTP_403_FORBIDDEN,
            )
        except ValidationError as exc:
            return Response(
                {"error": exc.message_dict},
                status=status.HTTP_400_BAD_REQUEST,
            )

        return Response(
            LeavePolicyPermissionReadSerializer(permission).data,
            status=status.HTTP_200_OK,
        )



def _policy_error_response(exc):
    if hasattr(exc, "message_dict"):
        detail = exc.message_dict
    else:
        detail = exc.messages

    return Response(
        {"error": detail},
        status=status.HTTP_400_BAD_REQUEST,
    )


class LeavePolicyListCreateAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            profile = require_policy_manager(request.user)
        except PermissionError as exc:
            return Response(
                {"error": str(exc)},
                status=status.HTTP_403_FORBIDDEN,
            )

        policies = LeavePolicy.objects.filter(
            organization_id=profile.organization_id,
        ).order_by("name")

        return Response(
            LeavePolicyReadSerializer(policies, many=True).data
        )

    def post(self, request):
        serializer = LeavePolicyCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            policy = create_leave_policy(
                user=request.user,
                **serializer.validated_data,
            )
        except PermissionError as exc:
            return Response(
                {"error": str(exc)},
                status=status.HTTP_403_FORBIDDEN,
            )
        except ValidationError as exc:
            return _policy_error_response(exc)

        return Response(
            LeavePolicyReadSerializer(policy).data,
            status=status.HTTP_201_CREATED,
        )


class LeavePolicyVersionCreateAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, policy_id):
        serializer = LeavePolicyVersionCreateSerializer(
            data=request.data
        )
        serializer.is_valid(raise_exception=True)

        try:
            version = create_policy_version(
                user=request.user,
                policy_id=policy_id,
                **serializer.validated_data,
            )
        except PermissionError as exc:
            return Response(
                {"error": str(exc)},
                status=status.HTTP_403_FORBIDDEN,
            )
        except ValidationError as exc:
            return _policy_error_response(exc)

        return Response(
            LeavePolicyVersionReadSerializer(version).data,
            status=status.HTTP_201_CREATED,
        )


class LeavePolicyRuleCreateAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, version_id):
        serializer = LeavePolicyRuleCreateSerializer(
            data=request.data
        )
        serializer.is_valid(raise_exception=True)

        try:
            rule = create_policy_rule(
                user=request.user,
                version_id=version_id,
                **serializer.validated_data,
            )
        except PermissionError as exc:
            return Response(
                {"error": str(exc)},
                status=status.HTTP_403_FORBIDDEN,
            )
        except ValidationError as exc:
            return _policy_error_response(exc)

        return Response(
            LeavePolicyRuleReadSerializer(rule).data,
            status=status.HTTP_201_CREATED,
        )


class LeavePolicyPublishAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, version_id):
        try:
            version = publish_policy_version(
                user=request.user,
                version_id=version_id,
            )
        except PermissionError as exc:
            return Response(
                {"error": str(exc)},
                status=status.HTTP_403_FORBIDDEN,
            )
        except ValidationError as exc:
            return _policy_error_response(exc)

        return Response(
            LeavePolicyVersionReadSerializer(version).data,
            status=status.HTTP_200_OK,
        )
