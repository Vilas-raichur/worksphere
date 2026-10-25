from django.urls import path

from leave_management.views import (
    LeaveManagerDecisionAPIView,
    LeaveManagerInboxAPIView,
    LeaveRequestListCreateAPIView,
    LeaveTypeDetailAPIView,
    LeaveTypeListAPIView,
    LeaveTypeManagementPolicyAPIView,
    LeaveRequestCancelAPIView,
    LeaveBalanceSummaryAPIView,
)

urlpatterns = [
    path("types/", LeaveTypeListAPIView.as_view(), name="leave-types"),
    path(
        "types/management-policy/",
        LeaveTypeManagementPolicyAPIView.as_view(),
        name="leave-type-management-policy",
    ),
    path(
        "types/<int:leave_type_id>/",
        LeaveTypeDetailAPIView.as_view(),
        name="leave-type-detail",
    ),
    path(
        "requests/",
        LeaveRequestListCreateAPIView.as_view(),
        name="leave-requests",
    ),
    path(
        "manager/inbox/",
        LeaveManagerInboxAPIView.as_view(),
        name="leave-manager-inbox",
    ),
    path(
        "manager/decision/",
        LeaveManagerDecisionAPIView.as_view(),
        name="leave-manager-decision",
    ),
    path(
    "requests/<int:leave_request_id>/cancel/",
    LeaveRequestCancelAPIView.as_view(),
    name="leave-request-cancel",
    ),
    path(
    "balance/",
    LeaveBalanceSummaryAPIView.as_view(),
    name="leave-balance-summary",
    ),
]