
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
from leave_management.policy_selection import (
    select_applicable_leave_rules,
)


class LeavePolicySelectionTests(TestCase):

    def setUp(self):
        self.organization = Organization.objects.create(
            name="Selection Test Organization",
            code="SELTEST",
        )

        self.other_organization = Organization.objects.create(
            name="Other Selection Organization",
            code="OTHERSEL",
        )

        self.leave_type = LeaveType.objects.create(
            organization=self.organization,
            code="CASUAL",
            name="Casual Leave",
        )

        self.other_leave_type = LeaveType.objects.create(
            organization=self.other_organization,
            code="CASUAL",
            name="Casual Leave",
        )
        from django.contrib.auth import get_user_model
        from accounts.models import UserProfile

        User = get_user_model()
        self.publishers = {}

        for organization in (
            self.organization,
            self.other_organization,
        ):
            user = User.objects.create_user(
                username=f"publisher_{organization.pk}",
                password="TestOnlyPassword123!",
            )
            profile = UserProfile.objects.create(
                user=user,
                organization=organization,
                role=UserProfile.Role.SUPER_ADMIN,
            )
            self.publishers[organization.pk] = profile

        self.allocation_date = date(2027, 3, 15)

    def create_rule(
        self,
        *,
        organization=None,
        leave_type=None,
        policy_code,
        priority=100,
        monthly_days="1.00",
        version_status=LeavePolicyVersion.Status.PUBLISHED,
        effective_from=date(2027, 1, 1),
        effective_until=None,
        policy_active=True,
        rule_active=True,
        department_id=None,
        designation_id=None,
        employee_type="",
        probation_condition=LeavePolicyRule.ProbationCondition.ANY,
    ):
        organization = organization or self.organization
        leave_type = leave_type or self.leave_type

        policy = LeavePolicy.objects.create(
            organization=organization,
            code=policy_code,
            name=f"{policy_code} Policy",
            is_active=policy_active,
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
            priority=priority,
            monthly_accrual_days=Decimal(monthly_days),
            department_id=department_id,
            designation_id=designation_id,
            employee_type=employee_type,
            probation_condition=probation_condition,
            is_active=rule_active,
        )

        if version_status == LeavePolicyVersion.Status.PUBLISHED:
            from django.utils import timezone

            publisher = self.publishers[organization.pk]
            version.status = LeavePolicyVersion.Status.PUBLISHED
            version.published_by = publisher
            version.published_at = timezone.now()
            version.save()

        return rule

    def select(self, **overrides):
        values = {
            "organization_id": self.organization.pk,
            "allocation_date": self.allocation_date,
            "department_id": None,
            "designation_id": None,
            "employee_type": "FULL_TIME",
            "in_probation": False,
        }
        values.update(overrides)

        return select_applicable_leave_rules(**values)

    def test_lower_priority_number_wins(self):
        high_number = self.create_rule(
            policy_code="GENERAL",
            priority=100,
            monthly_days="1.00",
        )

        low_number = self.create_rule(
            policy_code="SPECIAL",
            priority=10,
            monthly_days="2.00",
        )

        selected = self.select()

        self.assertEqual(
            selected[self.leave_type.pk].pk,
            low_number.pk,
        )
        self.assertNotEqual(
            selected[self.leave_type.pk].pk,
            high_number.pk,
        )

    def test_equal_priority_across_policies_is_rejected(self):
        self.create_rule(
            policy_code="FIRST",
            priority=50,
        )
        self.create_rule(
            policy_code="SECOND",
            priority=50,
        )

        with self.assertRaises(ValidationError):
            self.select()

    def test_draft_and_inactive_policies_are_excluded(self):
        self.create_rule(
            policy_code="DRAFT",
            version_status=LeavePolicyVersion.Status.DRAFT,
        )
        self.create_rule(
            policy_code="INACTIVE",
            policy_active=False,
        )
        self.create_rule(
            policy_code="INACTIVE_RULE",
            rule_active=False,
        )

        self.assertEqual(self.select(), {})

    def test_effective_dates_are_respected(self):
        self.create_rule(
            policy_code="FUTURE",
            effective_from=date(2027, 4, 1),
        )
        self.create_rule(
            policy_code="EXPIRED",
            effective_from=date(2027, 1, 1),
            effective_until=date(2027, 2, 28),
        )

        self.assertEqual(self.select(), {})

    def test_employee_type_is_respected(self):
        matching = self.create_rule(
            policy_code="FULLTIME",
            employee_type="FULL_TIME",
        )
        self.create_rule(
            policy_code="CONTRACT",
            employee_type="CONTRACT",
        )

        selected = self.select()

        self.assertEqual(
            selected[self.leave_type.pk].pk,
            matching.pk,
        )

    def test_probation_condition_is_respected(self):
        probation_rule = self.create_rule(
            policy_code="PROBATION",
            probation_condition=(
                LeavePolicyRule.ProbationCondition.IN_PROBATION
            ),
        )

        self.assertEqual(self.select(), {})

        selected = self.select(in_probation=True)

        self.assertEqual(
            selected[self.leave_type.pk].pk,
            probation_rule.pk,
        )

    def test_other_organization_rules_are_excluded(self):
        self.create_rule(
            organization=self.other_organization,
            leave_type=self.other_leave_type,
            policy_code="OTHERORG",
        )

        self.assertEqual(self.select(), {})

    def test_no_matching_policy_returns_empty_result(self):
        self.assertEqual(self.select(), {})
