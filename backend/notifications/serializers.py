from rest_framework import serializers

from .models import InAppNotification


class InAppNotificationReadSerializer(serializers.ModelSerializer):
    class Meta:
        model = InAppNotification
        fields = (
            "id",
            "category",
            "title",
            "message",
            "metadata",
            "read_at",
            "created_at",
        )
