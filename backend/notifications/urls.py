from django.urls import path

from .views import InAppNotificationListAPIView


urlpatterns = [
    path(
        "",
        InAppNotificationListAPIView.as_view(),
        name="in-app-notifications",
    ),
]
