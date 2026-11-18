from decimal import Decimal

from django.utils import timezone

from datetime import date
from django.core.exceptions import ValidationError

from django.core.exceptions import ValidationError

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient

from accounts.models import Organization, UserProfile
from leave_management.models import (
    LeavePolicy,
    LeavePolicyManagementPermission,
    LeavePolicyRule,
    LeavePolicyVersion,
    LeaveType,
)


User = get_user_model()


class LeavePolicyConfigurationTests(TestCase):
    def setUp(self):
        self.organization = Organization.objects.create(
            name="Policy Configuration Test Organization",
            code="POL_CONFIG",
        )
        self.other_organization = Organization.objects.create(
            name="Other Policy Configuration Organization",
            code="POL_CONFIG_OTHER",
        )

        self.super_admin = self.create_user(
            "config_super_admin",
            self.organization,
            UserProfile.Role.SUPER_ADMIN,
        )
        self.admin = self.create_user(
            "config_admin",
            self.organization,
            UserProfile.Role.ADMIN,
        )
        self.other_admin = self.create_user(
            "config_other_admin",
            self.other_organization,
            UserProfile.Role.ADMIN,
        )

        self.leave_type = LeaveType.objects.create(
            organization=self.organization,
            code="CL",
            name="Casual Leave",
        )

        self.client = APIClient()

    def create_user(self, username, organization, role):
        user = User.objects.create_user(
            username=username,
            password="TestPassword123!",
        )
        UserProfile.objects.create(
            user=user,
            organization=organization,
            role=role,
        )
        return user

    def create_published_policy_rule(
        self,
        *,
        organization,
        publisher,
        policy_code,
        leave_type,
        effective_from,
        effective_until=None,
        priority=100,
        probation_condition=LeavePolicyRule.ProbationCondition.ANY,
    ):
        policy = LeavePolicy.objects.create(
            organization=organization,
            code=policy_code,
            name=f"{policy_code} Policy",
        )

        version = LeavePolicyVersion.objects.create(
            policy=policy,
            version_number=1,
            effective_from=effective_from,
            effective_until=effective_until,
        )

        rule = LeavePolicyRule.objects.create(
            version=version,
            leave_type=leave_type,
            monthly_accrual_days="1.00",
            priority=priority,
            probation_condition=probation_condition,
        )

        version.status = LeavePolicyVersion.Status.PUBLISHED
        version.published_by = publisher.worksphere_profile
        version.published_at = timezone.now()
        version.save()

        return version, rule

    def test_super_admin_can_create_policy(self):
        self.client.force_authenticate(user=self.super_admin)

        response = self.client.post(
            reverse("leave-policies"),
            {
                "code": "GENERAL",
                "name": "General Leave Policy",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(LeavePolicy.objects.count(), 1)

    def test_unauthorized_admin_cannot_create_policy(self):
        self.client.force_authenticate(user=self.admin)

        response = self.client.post(
            reverse("leave-policies"),
            {
                "code": "GENERAL",
                "name": "General Leave Policy",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 403)

    def test_authorized_admin_can_create_policy(self):
        LeavePolicyManagementPermission.objects.create(
            organization=self.organization,
            admin_user=self.admin.worksphere_profile,
            granted_by=self.super_admin.worksphere_profile,
        )

        self.client.force_authenticate(user=self.admin)

        response = self.client.post(
            reverse("leave-policies"),
            {
                "code": "GENERAL",
                "name": "General Leave Policy",
            },
            format="json",
        )

        self.assertEqual(response.status_code, 201)

    def test_policy_version_rule_and_publication(self):
        self.client.force_authenticate(user=self.super_admin)

        policy_response = self.client.post(
            reverse("leave-policies"),
            {
                "code": "GENERAL",
                "name": "General Leave Policy",
            },
            format="json",
        )
        self.assertEqual(policy_response.status_code, 201)

        version_response = self.client.post(
            reverse(
                "leave-policy-version-create",
                kwargs={"policy_id": policy_response.data["id"]},
            ),
            {
                "version_number": 1,
                "effective_from": "2026-01-01",
            },
            format="json",
        )
        self.assertEqual(version_response.status_code, 201)

        version_id = version_response.data["id"]

        rule_response = self.client.post(
            reverse(
                "leave-policy-rule-create",
                kwargs={"version_id": version_id},
            ),
            {
                "leave_type_id": self.leave_type.pk,
                "monthly_accrual_days": "1.50",
                "accrual_timing": "MONTH_END",
            },
            format="json",
        )
        self.assertEqual(rule_response.status_code, 201)

        publish_response = self.client.post(
            reverse(
                "leave-policy-publish",
                kwargs={"version_id": version_id},
            ),
            {},
            format="json",
        )
        self.assertEqual(publish_response.status_code, 200)

        version = LeavePolicyVersion.objects.get(pk=version_id)
        self.assertEqual(
            version.status,
            LeavePolicyVersion.Status.PUBLISHED,
        )

    def test_publishing_without_rules_is_rejected(self):
        policy = LeavePolicy.objects.create(
            organization=self.organization,
            code="EMPTY",
            name="Empty Policy",
        )
        version = LeavePolicyVersion.objects.create(
            policy=policy,
            version_number=1,
            effective_from=date(2026, 1, 1),
        )

        self.client.force_authenticate(user=self.super_admin)

        response = self.client.post(
            reverse(
                "leave-policy-publish",
                kwargs={"version_id": version.pk},
            ),
            {},
            format="json",
        )

        self.assertEqual(response.status_code, 400)

    def test_published_version_rejects_new_rules(self):
        policy = LeavePolicy.objects.create(
            organization=self.organization,
            code="LOCKED",
            name="Locked Policy",
        )
        version = LeavePolicyVersion.objects.create(
            policy=policy,
            version_number=1,
            effective_from=date(2026, 1, 1),
        )
        LeavePolicyRule.objects.create(
            version=version,
            leave_type=self.leave_type,
            monthly_accrual_days="1.00",
        )

        self.client.force_authenticate(user=self.super_admin)

        publish_response = self.client.post(
            reverse(
                "leave-policy-publish",
                kwargs={"version_id": version.pk},
            ),
            {},
            format="json",
        )
        self.assertEqual(publish_response.status_code, 200)

        rule_response = self.client.post(
            reverse(
                "leave-policy-rule-create",
                kwargs={"version_id": version.pk},
            ),
            {
                "leave_type_id": self.leave_type.pk,
                "monthly_accrual_days": "2.00",
                "accrual_timing": "MONTH_START",
            },
            format="json",
        )

        self.assertEqual(rule_response.status_code, 400)


    def test_conflicting_rules_block_publication(self):
        policy = LeavePolicy.objects.create(
            organization=self.organization,
            code="CONFLICT",
            name="Conflicting Rules Policy",
        )

        version = LeavePolicyVersion.objects.create(
            policy=policy,
            version_number=1,
            effective_from=date(2027, 1, 1),
        )

        for amount in ("1.00", "2.00"):
            LeavePolicyRule.objects.create(
                version=version,
                leave_type=self.leave_type,
                monthly_accrual_days=amount,
                priority=100,
            )

        self.client.force_authenticate(
            user=self.super_admin
        )

        response = self.client.post(
            reverse(
                "leave-policy-publish",
                kwargs={"version_id": version.pk},
            ),
            {},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("rules", response.data["error"])

        version.refresh_from_db()
        self.assertEqual(
            version.status,
            LeavePolicyVersion.Status.DRAFT,
        )

    def test_different_priorities_do_not_conflict_at_publication(self):
        policy = LeavePolicy.objects.create(
            organization=self.organization,
            code="PRIORITY",
            name="Priority Rules Policy",
        )

        version = LeavePolicyVersion.objects.create(
            policy=policy,
            version_number=1,
            effective_from=date(2027, 1, 1),
        )

        for priority in (10, 100):
            LeavePolicyRule.objects.create(
                version=version,
                leave_type=self.leave_type,
                monthly_accrual_days="1.00",
                priority=priority,
            )

        self.client.force_authenticate(
            user=self.super_admin
        )

        response = self.client.post(
            reverse(
                "leave-policy-publish",
                kwargs={"version_id": version.pk},
            ),
            {},
            format="json",
        )

        self.assertEqual(response.status_code, 200)

    def test_inactive_leave_type_blocks_publication(self):
        policy = LeavePolicy.objects.create(
            organization=self.organization,
            code="INACTIVE_TYPE",
            name="Inactive Leave Type Policy",
        )

        version = LeavePolicyVersion.objects.create(
            policy=policy,
            version_number=1,
            effective_from=date(2027, 1, 1),
        )

        LeavePolicyRule.objects.create(
            version=version,
            leave_type=self.leave_type,
            monthly_accrual_days="1.00",
        )

        self.leave_type.is_active = False
        self.leave_type.save(update_fields=["is_active"])

        self.client.force_authenticate(
            user=self.super_admin
        )

        response = self.client.post(
            reverse(
                "leave-policy-publish",
                kwargs={"version_id": version.pk},
            ),
            {},
            format="json",
        )

        self.assertEqual(response.status_code, 400)

        version.refresh_from_db()
        self.assertEqual(
            version.status,
            LeavePolicyVersion.Status.DRAFT,
        )

    def test_published_version_cannot_be_modified_or_deleted(self):
        policy = LeavePolicy.objects.create(
            organization=self.organization,
            code="IMMUTABLE_VERSION",
            name="Immutable Version Policy",
        )

        version = LeavePolicyVersion.objects.create(
            policy=policy,
            version_number=1,
            effective_from=date(2027, 3, 1),
        )

        version.status = LeavePolicyVersion.Status.PUBLISHED
        version.published_by = self.super_admin.worksphere_profile
        version.published_at = timezone.now()
        version.save()

        version.effective_until = date(2027, 12, 31)

        with self.assertRaises(ValidationError):
            version.save()

        with self.assertRaises(ValidationError):
            version.delete()

        version.refresh_from_db()

        self.assertEqual(
            version.status,
            LeavePolicyVersion.Status.PUBLISHED,
        )

    def test_published_rule_cannot_be_modified_or_deleted(self):
        policy = LeavePolicy.objects.create(
            organization=self.organization,
            code="IMMUTABLE_RULE",
            name="Immutable Rule Policy",
        )

        version = LeavePolicyVersion.objects.create(
            policy=policy,
            version_number=1,
            effective_from=date(2027, 4, 1),
        )

        rule = LeavePolicyRule.objects.create(
            version=version,
            leave_type=self.leave_type,
            monthly_accrual_days="1.00",
        )

        version.status = LeavePolicyVersion.Status.PUBLISHED
        version.published_by = self.super_admin.worksphere_profile
        version.published_at = timezone.now()
        version.save()

        rule.monthly_accrual_days = "3.00"

        with self.assertRaises(ValidationError):
            rule.save()

        with self.assertRaises(ValidationError):
            rule.delete()

        rule.refresh_from_db()

        self.assertEqual(
            rule.monthly_accrual_days,
            Decimal("1.00"),
        )

    def test_cannot_add_rule_to_published_version(self):
        policy = LeavePolicy.objects.create(
            organization=self.organization,
            code="NO_NEW_RULE",
            name="No New Rule Policy",
        )

        version = LeavePolicyVersion.objects.create(
            policy=policy,
            version_number=1,
            effective_from=date(2027, 5, 1),
        )

        version.status = LeavePolicyVersion.Status.PUBLISHED
        version.published_by = self.super_admin.worksphere_profile
        version.published_at = timezone.now()
        version.save()

        rule = LeavePolicyRule(
            version=version,
            leave_type=self.leave_type,
            monthly_accrual_days="1.00",
        )

        with self.assertRaises(ValidationError):
            rule.save()

    def test_published_version_rejects_queryset_update_and_delete(self):
        policy = LeavePolicy.objects.create(
            organization=self.organization,
            code="BULK_VERSION",
            name="Bulk Version Protection",
        )

        version = LeavePolicyVersion.objects.create(
            policy=policy,
            version_number=1,
            effective_from=date(2027, 6, 1),
        )

        version.status = LeavePolicyVersion.Status.PUBLISHED
        version.published_by = self.super_admin.worksphere_profile
        version.published_at = timezone.now()
        version.save()

        with self.assertRaises(ValidationError):
            LeavePolicyVersion.objects.filter(
                pk=version.pk
            ).update(effective_until=date(2027, 12, 31))

        with self.assertRaises(ValidationError):
            LeavePolicyVersion.objects.filter(
                pk=version.pk
            ).delete()

    def test_published_rule_rejects_queryset_update_and_delete(self):
        policy = LeavePolicy.objects.create(
            organization=self.organization,
            code="BULK_RULE",
            name="Bulk Rule Protection",
        )

        version = LeavePolicyVersion.objects.create(
            policy=policy,
            version_number=1,
            effective_from=date(2027, 7, 1),
        )

        rule = LeavePolicyRule.objects.create(
            version=version,
            leave_type=self.leave_type,
            monthly_accrual_days="1.00",
        )

        version.status = LeavePolicyVersion.Status.PUBLISHED
        version.published_by = self.super_admin.worksphere_profile
        version.published_at = timezone.now()
        version.save()

        with self.assertRaises(ValidationError):
            LeavePolicyRule.objects.filter(
                pk=rule.pk
            ).update(monthly_accrual_days="5.00")

        with self.assertRaises(ValidationError):
            LeavePolicyRule.objects.filter(
                pk=rule.pk
            ).delete()

    def test_conflict_with_another_published_policy_blocks_publication(self):
        self.create_published_policy_rule(
            organization=self.organization,
            publisher=self.super_admin,
            policy_code="EXISTING",
            leave_type=self.leave_type,
            effective_from=date(2027, 1, 1),
            effective_until=date(2027, 12, 31),
            priority=100,
        )

        policy = LeavePolicy.objects.create(
            organization=self.organization,
            code="NEW_CONFLICT",
            name="New Conflicting Policy",
        )

        version = LeavePolicyVersion.objects.create(
            policy=policy,
            version_number=1,
            effective_from=date(2027, 6, 1),
            effective_until=date(2027, 12, 31),
        )

        LeavePolicyRule.objects.create(
            version=version,
            leave_type=self.leave_type,
            monthly_accrual_days="2.00",
            priority=100,
        )

        self.client.force_authenticate(user=self.super_admin)

        response = self.client.post(
            reverse(
                "leave-policy-publish",
                kwargs={"version_id": version.pk},
            ),
            {},
            format="json",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("rules", response.data["error"])

        version.refresh_from_db()
        self.assertEqual(
            version.status,
            LeavePolicyVersion.Status.DRAFT,
        )

    def test_cross_policy_rules_with_different_priorities_are_allowed(self):
        self.create_published_policy_rule(
            organization=self.organization,
            publisher=self.super_admin,
            policy_code="PRIORITY_EXISTING",
            leave_type=self.leave_type,
            effective_from=date(2027, 1, 1),
            effective_until=date(2027, 12, 31),
            priority=10,
        )

        policy = LeavePolicy.objects.create(
            organization=self.organization,
            code="PRIORITY_NEW",
            name="Priority New Policy",
        )

        version = LeavePolicyVersion.objects.create(
            policy=policy,
            version_number=1,
            effective_from=date(2027, 1, 1),
            effective_until=date(2027, 12, 31),
        )

        LeavePolicyRule.objects.create(
            version=version,
            leave_type=self.leave_type,
            monthly_accrual_days="2.00",
            priority=100,
        )

        self.client.force_authenticate(user=self.super_admin)

        response = self.client.post(
            reverse(
                "leave-policy-publish",
                kwargs={"version_id": version.pk},
            ),
            {},
            format="json",
        )

        self.assertEqual(response.status_code, 200)

    def test_cross_policy_non_overlapping_eligibility_is_allowed(self):
        self.create_published_policy_rule(
            organization=self.organization,
            publisher=self.super_admin,
            policy_code="PROBATION_EXISTING",
            leave_type=self.leave_type,
            effective_from=date(2027, 1, 1),
            effective_until=date(2027, 12, 31),
            probation_condition=(
                LeavePolicyRule.ProbationCondition.IN_PROBATION
            ),
        )

        policy = LeavePolicy.objects.create(
            organization=self.organization,
            code="PROBATION_NEW",
            name="Probation New Policy",
        )

        version = LeavePolicyVersion.objects.create(
            policy=policy,
            version_number=1,
            effective_from=date(2027, 1, 1),
            effective_until=date(2027, 12, 31),
        )

        LeavePolicyRule.objects.create(
            version=version,
            leave_type=self.leave_type,
            monthly_accrual_days="2.00",
            probation_condition=(
                LeavePolicyRule.ProbationCondition.COMPLETED
            ),
        )

        self.client.force_authenticate(user=self.super_admin)

        response = self.client.post(
            reverse(
                "leave-policy-publish",
                kwargs={"version_id": version.pk},
            ),
            {},
            format="json",
        )

        self.assertEqual(response.status_code, 200)

    def test_cross_policy_non_overlapping_effective_dates_are_allowed(self):
        self.create_published_policy_rule(
            organization=self.organization,
            publisher=self.super_admin,
            policy_code="DATES_EXISTING",
            leave_type=self.leave_type,
            effective_from=date(2027, 1, 1),
            effective_until=date(2027, 12, 31),
        )

        policy = LeavePolicy.objects.create(
            organization=self.organization,
            code="DATES_NEW",
            name="Dates New Policy",
        )

        version = LeavePolicyVersion.objects.create(
            policy=policy,
            version_number=1,
            effective_from=date(2028, 1, 1),
            effective_until=None,
        )

        LeavePolicyRule.objects.create(
            version=version,
            leave_type=self.leave_type,
            monthly_accrual_days="2.00",
        )

        self.client.force_authenticate(user=self.super_admin)

        response = self.client.post(
            reverse(
                "leave-policy-publish",
                kwargs={"version_id": version.pk},
            ),
            {},
            format="json",
        )

        self.assertEqual(response.status_code, 200)

    def test_another_organization_policy_does_not_cause_conflict(self):
        other_super_admin = self.create_user(
            "other_policy_super_admin",
            self.other_organization,
            UserProfile.Role.SUPER_ADMIN,
        )

        other_leave_type = LeaveType.objects.create(
            organization=self.other_organization,
            code="OTHER_CL",
            name="Other Casual Leave",
        )

        self.create_published_policy_rule(
            organization=self.other_organization,
            publisher=other_super_admin,
            policy_code="OTHER_ORG_POLICY",
            leave_type=other_leave_type,
            effective_from=date(2027, 1, 1),
            effective_until=date(2027, 12, 31),
            priority=100,
        )

        policy = LeavePolicy.objects.create(
            organization=self.organization,
            code="MY_ORG_POLICY",
            name="My Organization Policy",
        )

        version = LeavePolicyVersion.objects.create(
            policy=policy,
            version_number=1,
            effective_from=date(2027, 1, 1),
            effective_until=date(2027, 12, 31),
        )

        LeavePolicyRule.objects.create(
            version=version,
            leave_type=self.leave_type,
            monthly_accrual_days="2.00",
            priority=100,
        )

        self.client.force_authenticate(user=self.super_admin)

        response = self.client.post(
            reverse(
                "leave-policy-publish",
                kwargs={"version_id": version.pk},
            ),
            {},
            format="json",
        )

        self.assertEqual(response.status_code, 200)
