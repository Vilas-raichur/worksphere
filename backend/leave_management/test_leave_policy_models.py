
from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase

from accounts.models import Organization
from leave_management.models import (
    LeavePolicy,
    LeavePolicyRule,
    LeavePolicyVersion,
    LeaveType,
)


class LeavePolicyModelTests(TestCase):
    def setUp(self):
        self.organization = Organization.objects.create(
            name="Policy Model Test Organization",
            code="POL_MODEL",
        )

        self.other_organization = Organization.objects.create(
            name="Other Policy Model Organization",
            code="POL_OTHER",
        )

        self.policy = LeavePolicy.objects.create(
            organization=self.organization,
            code="GENERAL",
            name="General Leave Policy",
        )

        self.leave_type = LeaveType.objects.create(
            organization=self.organization,
            code="CL",
            name="Casual Leave",
        )

        self.version = LeavePolicyVersion.objects.create(
            policy=self.policy,
            version_number=1,
            effective_from=date(2026, 1, 1),
        )

    def test_draft_version_is_created(self):
        self.assertEqual(
            self.version.status,
            LeavePolicyVersion.Status.DRAFT,
        )
        self.assertEqual(self.version.version_number, 1)

    def test_invalid_version_dates_are_rejected(self):
        self.version.effective_until = date(2025, 12, 31)

        with self.assertRaises(ValidationError):
            self.version.full_clean()

    def test_monthly_accrual_rule_is_valid(self):
        rule = LeavePolicyRule(
            version=self.version,
            leave_type=self.leave_type,
            monthly_accrual_days=Decimal("1.50"),
            accrual_timing=(
                LeavePolicyRule.AccrualTiming.MONTH_END
            ),
        )

        rule.full_clean()
        rule.save()

        self.assertEqual(
            rule.monthly_accrual_days,
            Decimal("1.50"),
        )

    def test_negative_monthly_accrual_is_rejected(self):
        rule = LeavePolicyRule(
            version=self.version,
            leave_type=self.leave_type,
            monthly_accrual_days=Decimal("-1.00"),
        )

        with self.assertRaises(ValidationError):
            rule.full_clean()

    def test_cross_organization_leave_type_is_rejected(self):
        other_leave_type = LeaveType.objects.create(
            organization=self.other_organization,
            code="SL",
            name="Sick Leave",
        )

        rule = LeavePolicyRule(
            version=self.version,
            leave_type=other_leave_type,
            monthly_accrual_days=Decimal("2.00"),
        )

        with self.assertRaises(ValidationError):
            rule.full_clean()

    def test_disabled_carry_forward_rejects_positive_limit(self):
        rule = LeavePolicyRule(
            version=self.version,
            leave_type=self.leave_type,
            monthly_accrual_days=Decimal("1.00"),
            allow_carry_forward=False,
            carry_forward_limit_days=Decimal("5.00"),
        )

        with self.assertRaises(ValidationError):
            rule.full_clean()
