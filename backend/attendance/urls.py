from django.urls import path

from .views import (
    AttendanceTodayAPIView,
    AttendanceHistoryAPIView,
    AttendanceCheckInAPIView,
    AttendanceCheckOutAPIView,
    WFHRequestListCreateAPIView,
    WFHManagerInboxAPIView,
    WFHRequestApproveAPIView,
    WFHRequestRejectAPIView,
    AttendanceExceptionManagerInboxAPIView,
    AttendanceExceptionResolveAPIView,
)


urlpatterns = [
    path("today/", AttendanceTodayAPIView.as_view(), name="attendance-today"),
    path("history/", AttendanceHistoryAPIView.as_view(), name="attendance-history"),
    path("check-in/", AttendanceCheckInAPIView.as_view(), name="attendance-check-in"),
    path("check-out/", AttendanceCheckOutAPIView.as_view(), name="attendance-check-out"),
    path("wfh/requests/", WFHRequestListCreateAPIView.as_view(), name="wfh-requests"),
    path("wfh/manager/", WFHManagerInboxAPIView.as_view(), name="wfh-manager-inbox"),
    path("wfh/approve/", WFHRequestApproveAPIView.as_view(), name="wfh-approve"),
    path("wfh/reject/", WFHRequestRejectAPIView.as_view(), name="wfh-reject"),
    path(
        "exceptions/manager/",
        AttendanceExceptionManagerInboxAPIView.as_view(),
        name="attendance-exception-manager-inbox",
    ),
    path(
        "exceptions/review/",
        AttendanceExceptionResolveAPIView.as_view(),
        name="attendance-exception-review",
    ),
]