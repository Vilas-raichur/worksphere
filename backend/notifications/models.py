from django.conf import settings
from django.db import models


class InAppNotification(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="in_app_notifications",
    )
    organization = models.ForeignKey(
        "accounts.Organization",
        on_delete=models.PROTECT,
        related_name="in_app_notifications",
    )

    category = models.CharField(max_length=50)
    title = models.CharField(max_length=200)
    message = models.TextField()
    metadata = models.JSONField(default=dict, blank=True)
    read_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(
                fields=["user", "created_at"],
                name="inapp_user_created_idx",
            ),
            models.Index(
                fields=["user", "read_at"],
                name="inapp_user_read_idx",
            ),
        ]
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.title} - {self.user.username}"
