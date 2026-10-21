from .services import dispatch_notification


def dispatch_attendance_notification(
    *,
    user,
    organization,
    title,
    message,
    category,
    metadata=None,
    send_in_app=True,
    send_email=True,
):
    if organization is None:
        return None

    organization_id = getattr(
        organization,
        "pk",
        organization,
    )

    return dispatch_notification(
        user=user,
        organization_id=organization_id,
        title=title,
        message=message,
        category=category,
        metadata=metadata or {},
        send_in_app=send_in_app,
        send_email=send_email,
    )
