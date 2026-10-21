import logging

from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction

from .models import InAppNotification


logger = logging.getLogger(__name__)


def dispatch_notification(
    *,
    user,
    organization_id,
    title,
    message,
    category,
    metadata=None,
    send_in_app=True,
    send_email=True,
):
    """
    Deliver a notification to one user.

    In-app delivery and email delivery are isolated so that failure
    in one channel does not prevent an attempt through the other.
    """
    if user is None:
        return None

    notification = None

    if send_in_app:
        try:
            notification = InAppNotification.objects.create(
                user=user,
                organization_id=organization_id,
                category=category,
                title=title,
                message=message,
                metadata=metadata or {},
            )
        except Exception:
            logger.exception(
                "In-app notification failed for user id=%s",
                getattr(user, "pk", None),
            )

    recipient_email = getattr(user, "email", "")

    if send_email and recipient_email:
        try:
            send_mail(
                subject=title,
                message=message,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[recipient_email],
                fail_silently=False,
            )
        except Exception:
            logger.exception(
                "Email notification failed for user id=%s",
                getattr(user, "pk", None),
            )

    return notification


def schedule_notification(
    *,
    user,
    organization_id,
    title,
    message,
    category,
    metadata=None,
    send_in_app=True,
    send_email=True,
):
    """
    Dispatch only after the business transaction commits successfully.
    """
    if user is None:
        return

    def dispatch():
        dispatch_notification(
            user=user,
            organization_id=organization_id,
            title=title,
            message=message,
            category=category,
            metadata=metadata or {},
            send_in_app=send_in_app,
            send_email=send_email,
        )

    transaction.on_commit(dispatch)


def send_employee_activation_notification(
    *,
    employee,
    raw_token,
):
    activation_url = (
        f"{settings.WORKSPHERE_ACTIVATION_URL}"
        f"?token={raw_token}"
    )

    subject = "Activate your WorkSphere account"

    message = (
        f"Hello {employee.first_name} {employee.last_name},\n\n"
        "Your WorkSphere employee account has been created.\n\n"
        f"Onboarding Reference: {employee.onboarding_reference}\n\n"
        "Use the following secure link to activate your account:\n"
        f"{activation_url}\n\n"
        "This activation link expires according to your "
        "organization's configured activation policy.\n\n"
        "If you did not expect this email, please contact HR.\n\n"
        "Regards,\n"
        "WorkSphere"
    )

    if settings.DEBUG:
        print("\n" + "=" * 70)
        print("DEV ONLY - WorkSphere Activation Token")
        print(raw_token)
        print("=" * 70 + "\n")

    send_mail(
        subject=subject,
        message=message,
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[employee.official_email],
        fail_silently=False,
    )


def send_employee_activation_otp_notification(
    *,
    employee,
    otp_code,
    expires_at,
):
    subject = "Your WorkSphere activation OTP"

    message = (
        f"Hello {employee.first_name} {employee.last_name},\n\n"
        "Your WorkSphere account activation has been requested.\n\n"
        f"Your OTP is: {otp_code}\n\n"
        "This OTP is valid for 10 minutes.\n\n"
        "Do not share this OTP with anyone.\n\n"
        "If you did not request account activation, please contact HR.\n\n"
        "Regards,\n"
        "WorkSphere"
    )

    if settings.DEBUG:
        print("\n" + "=" * 70)
        print("DEV ONLY - WorkSphere Activation OTP")
        print(otp_code)
        print("=" * 70 + "\n")

    send_mail(
        subject=subject,
        message=message,
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[employee.official_email],
        fail_silently=False,
    )
