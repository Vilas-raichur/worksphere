from django.utils import timezone

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import InAppNotification
from .serializers import InAppNotificationReadSerializer


class InAppNotificationListAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        notifications = InAppNotification.objects.filter(
            user=request.user
        ).order_by("-created_at")[:50]

        return Response(
            InAppNotificationReadSerializer(
                notifications,
                many=True,
            ).data,
            status=status.HTTP_200_OK,
        )

    def post(self, request):
        try:
            notification_id = int(request.data.get("notification_id"))
            if notification_id < 1:
                raise ValueError
        except (TypeError, ValueError):
            return Response(
                {"error": "A positive integer notification_id is required."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            notification = InAppNotification.objects.get(
                id=notification_id,
                user=request.user,
            )
        except InAppNotification.DoesNotExist:
            return Response(
                {"error": "Notification does not exist."},
                status=status.HTTP_404_NOT_FOUND,
            )

        if notification.read_at is None:
            notification.read_at = timezone.now()
            notification.save(update_fields=["read_at"])

        return Response(
            {
                "message": "Notification marked as read.",
                "notification": InAppNotificationReadSerializer(
                    notification
                ).data,
            },
            status=status.HTTP_200_OK,
        )
