from unittest.mock import patch

from django.conf import settings
from django.contrib.auth import get_user_model
from django.test import TestCase

from accounts.models import Organization
from notifications.models import InAppNotification
from notifications.services import schedule_notification


User = get_user_model()


class NotificationDispatchTests(TestCase):
    def setUp(self):
        self.organization = Organization.objects.create(
            name="Notification Test Organization",
            code="NOTIFY",
        )

        self.user = User.objects.create_user(
            username="notification_test_user",
            email="notification-test@example.com",
            password="TestOnly-Valid-123!",
        )

    @patch("notifications.services.send_mail")
    def test_notification_creates_in_app_and_sends_email(
        self,
        mocked_send_mail,
    ):
        with self.captureOnCommitCallbacks(execute=True) as callbacks:
            schedule_notification(
                user=self.user,
                organization_id=self.organization.id,
                title="Test notification",
                message="This is a notification test.",
                category="LEAVE",
                metadata={"event": "test"},
            )

        self.assertEqual(len(callbacks), 1)

        notification = InAppNotification.objects.get(
            user=self.user,
            title="Test notification",
        )

        self.assertEqual(notification.organization_id, self.organization.id)
        self.assertEqual(notification.category, "LEAVE")
        self.assertEqual(
            notification.metadata,
            {"event": "test"},
        )

        mocked_send_mail.assert_called_once_with(
            subject="Test notification",
            message="This is a notification test.",
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=["notification-test@example.com"],
            fail_silently=False,
        )
