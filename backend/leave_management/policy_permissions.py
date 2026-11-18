
from django.core.exceptions import ValidationError
from django.db import transaction

from accounts.models import UserProfile
from leave_management.models import LeavePolicyManagementPermission


def require_policy_super_admin(user):
    try:
        profile = user.worksphere_profile
    except UserProfile.DoesNotExist:
        raise PermissionError(
            "Only the organization's Super Admin can manage "
            "leave-policy permissions."
        )

    if profile.role != UserProfile.Role.SUPER_ADMIN:
        raise PermissionError(
            "Only the organization's Super Admin can manage "
            "leave-policy permissions."
        )

    if not profile.organization.is_active:
        raise PermissionError("The organization is inactive.")

    return profile


def can_manage_leave_policies(user):
    if not user.is_authenticated or not user.is_active:
        return False

    try:
        profile = user.worksphere_profile
    except UserProfile.DoesNotExist:
        return False

    if not profile.organization.is_active:
        return False

    if profile.role == UserProfile.Role.SUPER_ADMIN:
        return True

    if profile.role != UserProfile.Role.ADMIN:
        return False

    return LeavePolicyManagementPermission.objects.filter(
        organization_id=profile.organization_id,
        admin_user=profile,
        is_active=True,
    ).exists()


@transaction.atomic
def grant_leave_policy_permission(*, granted_by, admin_profile_id):
    super_admin = require_policy_super_admin(granted_by)

    try:
        admin_profile = UserProfile.objects.get(
            pk=admin_profile_id,
            organization_id=super_admin.organization_id,
            role=UserProfile.Role.ADMIN,
        )
    except UserProfile.DoesNotExist:
        raise ValidationError(
            {
                "admin_profile_id": (
                    "No eligible Admin profile exists in "
                    "your organization."
                )
            }
        )

    permission, _ = (
        LeavePolicyManagementPermission.objects.select_for_update()
        .get_or_create(
            organization=super_admin.organization,
            admin_user=admin_profile,
            defaults={
                "granted_by": super_admin,
                "is_active": True,
            },
        )
    )

    permission.granted_by = super_admin
    permission.is_active = True
    permission.full_clean()
    permission.save()

    return permission


@transaction.atomic
def revoke_leave_policy_permission(*, revoked_by, permission_id):
    super_admin = require_policy_super_admin(revoked_by)

    try:
        permission = (
            LeavePolicyManagementPermission.objects.select_for_update()
            .get(
                pk=permission_id,
                organization_id=super_admin.organization_id,
            )
        )
    except LeavePolicyManagementPermission.DoesNotExist:
        raise ValidationError(
            {"permission_id": "Permission grant was not found."}
        )

    permission.is_active = False
    permission.full_clean()
    permission.save(update_fields=["is_active", "updated_at"])

    return permission
