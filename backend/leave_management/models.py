from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import F, Q


class LeaveType(models.Model):
    organization = models.ForeignKey(
        "accounts.Organization",
        on_delete=models.CASCADE,
        related_name="leave_types",
    )
    code = models.CharField(max_length=30)
    name = models.CharField(max_length=100)
    is_paid = models.BooleanField(default=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "code"],
                name="uniq_leave_type_org_code",
            ),
        ]

    def __str__(self):
        return f"{self.organization} - {self.name}"


class LeaveRequest(models.Model):
    class Status(models.TextChoices):
        PENDING = "PENDING", "Pending"
        APPROVED = "APPROVED", "Approved"
        REJECTED = "REJECTED", "Rejected"
        CANCELLED = "CANCELLED", "Cancelled"

    organization = models.ForeignKey(
        "accounts.Organization",
        on_delete=models.PROTECT,
        related_name="leave_requests",
    )
    employee = models.ForeignKey(
        "employees.Employee",
        on_delete=models.PROTECT,
        related_name="leave_requests",
    )
    leave_type = models.ForeignKey(
        LeaveType,
        on_delete=models.PROTECT,
        related_name="requests",
    )

    # Preserve the department/designation at the time of the request.
    department_id_snapshot = models.PositiveIntegerField(
        null=True,
        blank=True,
    )
    designation_id_snapshot = models.PositiveIntegerField(
        null=True,
        blank=True,
    )

    # Approval goes to the employee's assigned manager at submission time.
    manager_at_request = models.ForeignKey(
        "employees.Employee",
        on_delete=models.PROTECT,
        related_name="leave_requests_for_review",
    )

    start_date = models.DateField()
    end_date = models.DateField()
    working_days_count = models.PositiveSmallIntegerField()
    reason = models.TextField()

    status = models.CharField(
        max_length=12,
        choices=Status.choices,
        default=Status.PENDING,
    )

    reviewed_by = models.ForeignKey(
        "employees.Employee",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="leave_requests_reviewed",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_remarks = models.TextField(blank=True, default="")

    requested_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-requested_at"]
        constraints = [
            models.CheckConstraint(
                condition=Q(end_date__gte=F("start_date")),
                name="leave_request_end_on_or_after_start",
            ),
            models.CheckConstraint(
                condition=Q(working_days_count__gt=0),
                name="leave_request_positive_workdays",
            ),
        ]

    def __str__(self):
        return (
            f"{self.employee} - {self.leave_type.name} "
            f"({self.start_date} to {self.end_date})"
        )



class LeaveBalance(models.Model):
    organization = models.ForeignKey(
        "accounts.Organization",
        on_delete=models.PROTECT,
        related_name="leave_balances",
    )
    employee = models.ForeignKey(
        "employees.Employee",
        on_delete=models.PROTECT,
        related_name="leave_balances",
    )
    leave_type = models.ForeignKey(
        LeaveType,
        on_delete=models.PROTECT,
        related_name="balances",
    )

    period_start = models.DateField()
    period_end = models.DateField()
    entitled_days = models.DecimalField(
        max_digits=7,
        decimal_places=2,
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["period_start", "employee_id"]
        constraints = [
            models.UniqueConstraint(
                fields=[
                    "employee",
                    "leave_type",
                    "period_start",
                    "period_end",
                ],
                name="uniq_leave_balance_period",
            ),
            models.CheckConstraint(
                condition=Q(
                    period_end__gte=F("period_start")
                ),
                name="leave_balance_period_valid",
            ),
            models.CheckConstraint(
                condition=Q(entitled_days__gte=0),
                name="leave_balance_nonnegative_entitlement",
            ),
        ]

    def clean(self):
        super().clean()

        errors = {}

        if (
            self.entitled_days is not None
            and self.entitled_days < 0
        ):
            errors["entitled_days"] = (
                "Entitled days cannot be negative."
            )

        if self.period_start and self.period_end:
            if self.period_end < self.period_start:
                errors["period_end"] = (
                    "The period end date cannot be before "
                    "the period start date."
                )

        if (
            self.organization_id
            and self.employee_id
            and self.employee.organization_id != self.organization_id
        ):
            errors["employee"] = (
                "The employee must belong to the selected organization."
            )

        if (
            self.organization_id
            and self.leave_type_id
            and self.leave_type.organization_id != self.organization_id
        ):
            errors["leave_type"] = (
                "The leave type must belong to the selected organization."
            )

        if (
            self.employee_id
            and self.leave_type_id
            and self.period_start
            and self.period_end
            and self.period_end >= self.period_start
        ):
            overlapping = LeaveBalance.objects.filter(
                employee_id=self.employee_id,
                leave_type_id=self.leave_type_id,
                period_start__lte=self.period_end,
                period_end__gte=self.period_start,
            )

            if self.pk:
                overlapping = overlapping.exclude(pk=self.pk)

            if overlapping.exists():
                errors["period_start"] = (
                    "An existing balance period overlaps this period "
                    "for the same employee and leave type."
                )

        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return (
            f"{self.employee} - {self.leave_type.name} "
            f"({self.period_start} to {self.period_end})"
        )


class LeaveBalanceTransactionQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise ValidationError(
            "Leave balance transactions cannot be bulk updated."
        )

    def delete(self):
        raise ValidationError(
            "Leave balance transactions cannot be bulk deleted."
        )

    def bulk_create(self, *args, **kwargs):
        raise ValidationError(
            "Use the leave transaction service to create transactions."
        )


class LeaveBalanceTransaction(models.Model):
    class TransactionType(models.TextChoices):
        ALLOCATION = "ALLOCATION", "Initial allocation"
        ACCRUAL = "ACCRUAL", "Monthly accrual"
        CARRY_FORWARD = "CARRY_FORWARD", "Carry forward"
        EXPIRY = "EXPIRY", "Expiry"
        ADJUSTMENT = "ADJUSTMENT", "Manual adjustment"
        LEAVE_DEBIT = "LEAVE_DEBIT", "Approved leave deduction"
        LEAVE_CREDIT = "LEAVE_CREDIT", "Leave deduction reversal"

    objects = LeaveBalanceTransactionQuerySet.as_manager()

    organization = models.ForeignKey(
        "accounts.Organization",
        on_delete=models.PROTECT,
        related_name="leave_balance_transactions",
    )
    employee = models.ForeignKey(
        "employees.Employee",
        on_delete=models.PROTECT,
        related_name="leave_balance_transactions",
    )
    leave_type = models.ForeignKey(
        LeaveType,
        on_delete=models.PROTECT,
        related_name="balance_transactions",
    )
    balance = models.ForeignKey(
        LeaveBalance,
        on_delete=models.PROTECT,
        related_name="transactions",
    )

    transaction_type = models.CharField(
        max_length=20,
        choices=TransactionType.choices,
    )

    # Positive days add to the balance.
    # Negative days reduce the balance.
    days = models.DecimalField(
        max_digits=7,
        decimal_places=2,
    )

    effective_date = models.DateField()

    policy_version = models.ForeignKey(
        "leave_management.LeavePolicyVersion",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="balance_transactions",
    )
    policy_rule = models.ForeignKey(
        "leave_management.LeavePolicyRule",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="balance_transactions",
    )
    leave_request = models.ForeignKey(
        LeaveRequest,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="balance_transactions",
    )

    idempotency_key = models.CharField(
        max_length=255,
        unique=True,
    )
    description = models.CharField(
        max_length=255,
        blank=True,
        default="",
    )
    created_by = models.ForeignKey(
        "auth.User",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="created_leave_balance_transactions",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["effective_date", "created_at", "id"]
        constraints = [
            models.CheckConstraint(
                condition=~models.Q(days=0),
                name="leave_balance_transaction_nonzero_days",
            ),
        ]

    def clean(self):
        super().clean()
        errors = {}

        if self.days is not None and self.days == 0:
            errors["days"] = "A transaction must change the balance."

        if (
            self.organization_id
            and self.employee_id
            and self.employee.organization_id != self.organization_id
        ):
            errors["employee"] = (
                "The employee must belong to the transaction organization."
            )

        if (
            self.organization_id
            and self.leave_type_id
            and self.leave_type.organization_id != self.organization_id
        ):
            errors["leave_type"] = (
                "The leave type must belong to the transaction organization."
            )

        if self.balance_id:
            if (
                self.balance.organization_id != self.organization_id
                or self.balance.employee_id != self.employee_id
                or self.balance.leave_type_id != self.leave_type_id
            ):
                errors["balance"] = (
                    "The balance must match the transaction organization, "
                    "employee and leave type."
                )

        if self.policy_rule_id:
            if not self.policy_version_id:
                errors["policy_version"] = (
                    "A policy version is required when a policy rule is set."
                )
            elif self.policy_rule.version_id != self.policy_version_id:
                errors["policy_rule"] = (
                    "The policy rule must belong to the selected version."
                )

        if self.policy_version_id:
            if (
                self.policy_version.policy.organization_id
                != self.organization_id
            ):
                errors["policy_version"] = (
                    "The policy version must belong to the transaction "
                    "organization."
                )

        if self.leave_request_id:
            if (
                self.leave_request.organization_id != self.organization_id
                or self.leave_request.employee_id != self.employee_id
                or self.leave_request.leave_type_id != self.leave_type_id
            ):
                errors["leave_request"] = (
                    "The leave request must match the transaction "
                    "organization, employee and leave type."
                )

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise ValidationError(
                "Leave balance transactions are immutable."
            )

        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError(
            "Leave balance transactions cannot be deleted."
        )

    def __str__(self):
        return (
            f"{self.employee} - {self.transaction_type} "
            f"({self.days} days on {self.effective_date})"
        )


class LeavePolicyManagementPermission(models.Model):
    organization = models.ForeignKey(
        "accounts.Organization",
        on_delete=models.PROTECT,
        related_name="leave_policy_management_permissions",
    )
    admin_user = models.ForeignKey(
        "accounts.UserProfile",
        on_delete=models.PROTECT,
        related_name="leave_policy_management_grants",
    )
    granted_by = models.ForeignKey(
        "accounts.UserProfile",
        on_delete=models.PROTECT,
        related_name="granted_leave_policy_permissions",
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "admin_user"],
                name="uniq_leave_policy_admin_permission",
            ),
        ]

    def clean(self):
        super().clean()

        if not self.organization_id:
            return

        if self.admin_user_id:
            if (
                self.admin_user.organization_id != self.organization_id
                or self.admin_user.role != "ADMIN"
            ):
                raise ValidationError(
                    {
                        "admin_user": (
                            "Permission can only be granted to an "
                            "Admin belonging to this organization."
                        )
                    }
                )

        if self.granted_by_id:
            if (
                self.granted_by.organization_id != self.organization_id
                or self.granted_by.role != "SUPER_ADMIN"
            ):
                raise ValidationError(
                    {
                        "granted_by": (
                            "Only this organization's Super Admin "
                            "can grant leave-policy permissions."
                        )
                    }
                )


class LeavePolicy(models.Model):
    organization = models.ForeignKey(
        "accounts.Organization",
        on_delete=models.PROTECT,
        related_name="leave_policies",
    )
    code = models.CharField(max_length=30)
    name = models.CharField(max_length=150)
    description = models.TextField(blank=True, default="")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "code"],
                name="uniq_leave_policy_org_code",
            ),
        ]

    def __str__(self):
        return f"{self.organization.code} - {self.code}"


class LeavePolicyVersionQuerySet(models.QuerySet):
    def update(self, **kwargs):
        if self.filter(
            status=LeavePolicyVersion.Status.PUBLISHED
        ).exists():
            raise ValidationError(
                "Published policy versions cannot be bulk updated."
            )

        if kwargs.get("status") == LeavePolicyVersion.Status.PUBLISHED:
            raise ValidationError(
                "Use the policy publication service to publish versions."
            )

        return super().update(**kwargs)

    def delete(self):
        if self.filter(
            status=LeavePolicyVersion.Status.PUBLISHED
        ).exists():
            raise ValidationError(
                "Published policy versions cannot be bulk deleted."
            )

        return super().delete()


class LeavePolicyRuleQuerySet(models.QuerySet):
    def update(self, **kwargs):
        if self.filter(
            version__status=LeavePolicyVersion.Status.PUBLISHED
        ).exists():
            raise ValidationError(
                "Rules belonging to published versions "
                "cannot be bulk updated."
            )

        return super().update(**kwargs)

    def delete(self):
        if self.filter(
            version__status=LeavePolicyVersion.Status.PUBLISHED
        ).exists():
            raise ValidationError(
                "Rules belonging to published versions "
                "cannot be bulk deleted."
            )

        return super().delete()


class LeavePolicyVersion(models.Model):
    class Status(models.TextChoices):
        DRAFT = "DRAFT", "Draft"
        PUBLISHED = "PUBLISHED", "Published"

    objects = LeavePolicyVersionQuerySet.as_manager()

    policy = models.ForeignKey(
        LeavePolicy,
        on_delete=models.PROTECT,
        related_name="versions",
    )
    version_number = models.PositiveIntegerField()
    status = models.CharField(
        max_length=12,
        choices=Status.choices,
        default=Status.DRAFT,
    )
    effective_from = models.DateField()
    effective_until = models.DateField(
        null=True,
        blank=True,
    )
    published_by = models.ForeignKey(
        "accounts.UserProfile",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="published_leave_policy_versions",
    )
    published_at = models.DateTimeField(
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["policy_id", "-version_number"]
        constraints = [
            models.UniqueConstraint(
                fields=["policy", "version_number"],
                name="uniq_leave_policy_version",
            ),
            models.CheckConstraint(
                condition=(
                    models.Q(effective_until__isnull=True)
                    | models.Q(
                        effective_until__gte=models.F(
                            "effective_from"
                        )
                    )
                ),
                name="leave_policy_version_valid_dates",
            ),
        ]

    def clean(self):
        super().clean()
        errors = {}

        if (
            self.effective_from
            and self.effective_until
            and self.effective_until < self.effective_from
        ):
            errors["effective_until"] = (
                "Effective end date cannot be earlier "
                "than the start date."
            )

        if self.status == self.Status.PUBLISHED:
            if not self.published_by_id or not self.published_at:
                errors["status"] = (
                    "A published version requires publication "
                    "details."
                )

        if self.published_by_id and self.policy_id:
            if (
                self.published_by.organization_id
                != self.policy.organization_id
            ):
                errors["published_by"] = (
                    "The publisher must belong to "
                    "the policy organization."
                )

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if self.pk is not None:
            original = type(self).objects.filter(
                pk=self.pk
            ).values("status").first()

            if original is not None:
                if original["status"] == self.Status.PUBLISHED:
                    raise ValidationError({
                        "status": (
                            "Published leave policy versions "
                            "cannot be modified."
                        )
                    })

                if (
                    self.status == self.Status.PUBLISHED
                    and original["status"] != self.Status.DRAFT
                ):
                    raise ValidationError({
                        "status": "Invalid policy status transition."
                    })

        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.pk is not None:
            if type(self).objects.filter(
                pk=self.pk,
                status=self.Status.PUBLISHED,
            ).exists():
                raise ValidationError({
                    "status": (
                        "Published leave policy versions "
                        "cannot be deleted."
                    )
                })

        return super().delete(*args, **kwargs)

    def __str__(self):
        return (
            f"{self.policy.code} - "
            f"Version {self.version_number}"
        )


class LeavePolicyRule(models.Model):
    class AccrualTiming(models.TextChoices):
        MONTH_START = "MONTH_START", "Start of month"
        MONTH_END = "MONTH_END", "End of month"

    objects = LeavePolicyRuleQuerySet.as_manager()

    class ProbationCondition(models.TextChoices):
        ANY = "ANY", "Any probation status"
        IN_PROBATION = "IN_PROBATION", "In probation"
        COMPLETED = "COMPLETED", "Probation completed"

    version = models.ForeignKey(
        LeavePolicyVersion,
        on_delete=models.PROTECT,
        related_name="rules",
    )
    leave_type = models.ForeignKey(
        LeaveType,
        on_delete=models.PROTECT,
        related_name="policy_rules",
    )
    department = models.ForeignKey(
        "employees.Department",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="leave_policy_rules",
    )
    designation = models.ForeignKey(
        "employees.Designation",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="leave_policy_rules",
    )
    employee_type = models.CharField(
        max_length=50,
        blank=True,
        default="",
    )
    probation_condition = models.CharField(
        max_length=20,
        choices=ProbationCondition.choices,
        default=ProbationCondition.ANY,
    )
    priority = models.PositiveIntegerField(default=100)
    monthly_accrual_days = models.DecimalField(
        max_digits=6,
        decimal_places=2,
    )
    accrual_timing = models.CharField(
        max_length=20,
        choices=AccrualTiming.choices,
        default=AccrualTiming.MONTH_START,
    )
    allow_carry_forward = models.BooleanField(default=False)
    carry_forward_limit_days = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        default=Decimal("0.00"),
    )
    carry_forward_interval_months = (
        models.PositiveSmallIntegerField(
            null=True,
            blank=True,
        )
    )
    carry_forward_expiry_months = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["priority", "id"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(monthly_accrual_days__gte=0),
                name="leave_policy_rule_nonnegative_accrual",
            ),
            models.CheckConstraint(
                condition=models.Q(carry_forward_limit_days__gte=0),
                name="leave_policy_rule_nonnegative_carry",
            ),
        ]

    def clean(self):
        super().clean()
        errors = {}

        if self.version_id and self.leave_type_id:
            if (
                self.version.policy.organization_id
                != self.leave_type.organization_id
            ):
                errors["leave_type"] = (
                    "The leave type and policy must belong "
                    "to the same organization."
                )

        if (
            self.monthly_accrual_days is not None
            and self.monthly_accrual_days < 0
        ):
            errors["monthly_accrual_days"] = (
                "Monthly accrual cannot be negative."
            )

        if (
            self.carry_forward_limit_days is not None
            and self.carry_forward_limit_days < 0
        ):
            errors["carry_forward_limit_days"] = (
                "Carry-forward limit cannot be negative."
            )

        if not self.allow_carry_forward:
            if self.carry_forward_limit_days != 0:
                errors["carry_forward_limit_days"] = (
                    "Carry-forward limit must be zero "
                    "when carry-forward is disabled."
                )

            if self.carry_forward_interval_months is not None:
                errors["carry_forward_interval_months"] = (
                    "Carry-forward interval must be empty "
                    "when carry-forward is disabled."
                )

            if self.carry_forward_expiry_months is not None:
                errors["carry_forward_expiry_months"] = (
                    "Carry-forward expiry must be empty "
                    "when carry-forward is disabled."
                )

        else:
            if (
                self.carry_forward_limit_days is None
                or self.carry_forward_limit_days <= 0
            ):
                errors["carry_forward_limit_days"] = (
                    "A positive carry-forward limit is required."
                )

            if (
                self.carry_forward_interval_months is None
                or not 1 <= self.carry_forward_interval_months <= 12
                or 12 % self.carry_forward_interval_months != 0
            ):
                errors["carry_forward_interval_months"] = (
                    "Carry-forward interval must be a divisor "
                    "of 12 between 1 and 12 months."
                )

            if (
                self.carry_forward_expiry_months is None
                or self.carry_forward_expiry_months <= 0
            ):
                errors["carry_forward_expiry_months"] = (
                    "A positive expiry period is required."
                )

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if self.pk is not None:
            original = type(self).objects.filter(
                pk=self.pk
            ).values("version_id").first()

            if original is not None:
                original_is_published = (
                    LeavePolicyVersion.objects.filter(
                        pk=original["version_id"],
                        status=LeavePolicyVersion.Status.PUBLISHED,
                    ).exists()
                )

                if original_is_published:
                    raise ValidationError({
                        "version": (
                            "Rules belonging to published "
                            "policy versions cannot be modified."
                        )
                    })

        if self.version_id is not None:
            if LeavePolicyVersion.objects.filter(
                pk=self.version_id,
                status=LeavePolicyVersion.Status.PUBLISHED,
            ).exists():
                raise ValidationError({
                    "version": (
                        "Rules cannot be added or moved "
                        "to published policy versions."
                    )
                })

        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if self.pk is not None:
            if type(self).objects.filter(
                pk=self.pk,
                version__status=LeavePolicyVersion.Status.PUBLISHED,
            ).exists():
                raise ValidationError({
                    "version": (
                        "Rules belonging to published "
                        "policy versions cannot be deleted."
                    )
                })

        return super().delete(*args, **kwargs)

    def __str__(self):
        return (
            f"{self.version} - "
            f"{self.leave_type.code} - "
            f"Priority {self.priority}"
        )


class LeaveCarryForwardLot(models.Model):
    """
    Tracks a carried-forward portion of leave independently
    so that it can be consumed and expired separately.
    """

    balance = models.ForeignKey(
        LeaveBalance,
        on_delete=models.PROTECT,
        related_name="carry_forward_lots",
    )
    policy_version = models.ForeignKey(
        LeavePolicyVersion,
        on_delete=models.PROTECT,
        related_name="carry_forward_lots",
    )
    policy_rule = models.ForeignKey(
        LeavePolicyRule,
        on_delete=models.PROTECT,
        related_name="carry_forward_lots",
    )

    source_period_start = models.DateField()
    source_period_end = models.DateField()
    carried_forward_on = models.DateField()
    expires_on = models.DateField()

    granted_days = models.DecimalField(
        max_digits=7,
        decimal_places=2,
    )
    remaining_days = models.DecimalField(
        max_digits=7,
        decimal_places=2,
    )

    idempotency_key = models.CharField(
        max_length=255,
        unique=True,
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["expires_on", "id"]
        constraints = [
            models.CheckConstraint(
                condition=Q(granted_days__gt=0),
                name="leave_cf_lot_positive_grant",
            ),
            models.CheckConstraint(
                condition=Q(remaining_days__gte=0),
                name="leave_cf_lot_nonnegative_remaining",
            ),
            models.CheckConstraint(
                condition=Q(remaining_days__lte=F("granted_days")),
                name="leave_cf_lot_remaining_within_grant",
            ),
            models.CheckConstraint(
                condition=Q(expires_on__gt=F("carried_forward_on")),
                name="leave_cf_lot_valid_expiry",
            ),
        ]

    def clean(self):
        super().clean()
        errors = {}

        balance = self.balance if self.balance_id else None
        version = (
            self.policy_version
            if self.policy_version_id
            else None
        )
        rule = self.policy_rule if self.policy_rule_id else None

        if self.source_period_start and self.source_period_end:
            if self.source_period_start > self.source_period_end:
                errors["source_period_end"] = (
                    "Source period end cannot be before its start."
                )

        if (
            self.source_period_end
            and self.carried_forward_on
            and self.carried_forward_on <= self.source_period_end
        ):
            errors["carried_forward_on"] = (
                "Carry-forward date must be after the source period ends."
            )

        if (
            self.carried_forward_on
            and self.expires_on
            and self.expires_on <= self.carried_forward_on
        ):
            errors["expires_on"] = (
                "Expiry date must be after the carry-forward date."
            )

        if balance is not None:
            if (
                self.source_period_start
                and self.source_period_start < balance.period_start
            ):
                errors["source_period_start"] = (
                    "Source period cannot start before the balance period."
                )

            if (
                self.source_period_end
                and self.source_period_end > balance.period_end
            ):
                errors["source_period_end"] = (
                    "Source period cannot end after the balance period."
                )

            if (
                self.granted_days is not None
                and self.granted_days <= 0
            ):
                errors["granted_days"] = (
                    "Granted carry-forward days must be positive."
                )

            if (
                self.remaining_days is not None
                and self.granted_days is not None
                and (
                    self.remaining_days < 0
                    or self.remaining_days > self.granted_days
                )
            ):
                errors["remaining_days"] = (
                    "Remaining days must be between zero "
                    "and the originally granted days."
                )

        if version is not None and balance is not None:
            policy_organization_id = (
                version.policy.organization_id
            )

            if policy_organization_id != balance.organization_id:
                errors["policy_version"] = (
                    "The policy and balance must belong "
                    "to the same organization."
                )

            if version.status != LeavePolicyVersion.Status.PUBLISHED:
                errors["policy_version"] = (
                    "Carry-forward lots must reference "
                    "a published policy version."
                )

        if rule is not None:
            if self.policy_version_id and rule.version_id != self.policy_version_id:
                errors["policy_rule"] = (
                    "The policy rule must belong to the selected policy version."
                )

            if balance is not None:
                if rule.leave_type_id != balance.leave_type_id:
                    errors["policy_rule"] = (
                        "The policy rule and balance must use "
                        "the same leave type."
                    )

                if (
                    rule.version.policy.organization_id
                    != balance.organization_id
                ):
                    errors["policy_rule"] = (
                        "The policy rule and balance must belong "
                        "to the same organization."
                    )

            if not rule.allow_carry_forward:
                errors["policy_rule"] = (
                    "The selected policy rule does not allow carry-forward."
                )

            if (
                rule.carry_forward_limit_days is not None
                and self.granted_days is not None
                and self.granted_days > rule.carry_forward_limit_days
            ):
                errors["granted_days"] = (
                    "Granted days cannot exceed the policy rule's "
                    "carry-forward limit."
                )

        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return (
            f"{self.balance.employee} - "
            f"{self.remaining_days}/{self.granted_days} "
            f"days - expires {self.expires_on}"
        )


class LeaveCarryForwardConsumption(models.Model):
    """
    An immutable event recording carry-forward leave consumed
    by one approved leave request on one working date.
    """

    lot = models.ForeignKey(
        LeaveCarryForwardLot,
        on_delete=models.PROTECT,
        related_name="consumptions",
    )
    leave_request = models.ForeignKey(
        LeaveRequest,
        on_delete=models.PROTECT,
        related_name="carry_forward_consumptions",
    )
    consumed_on = models.DateField()
    allocated_days = models.DecimalField(
        max_digits=6,
        decimal_places=2,
    )
    idempotency_key = models.CharField(
        max_length=255,
        unique=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["consumed_on", "lot__expires_on", "id"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(allocated_days__gt=0),
                name="carry_forward_consumption_positive",
            ),
        ]

    def clean(self):
        super().clean()
        errors = {}

        if self.lot_id and self.leave_request_id:
            lot = self.lot
            request = self.leave_request

            if lot.balance.employee_id != request.employee_id:
                errors["leave_request"] = (
                    "The leave request and carry-forward lot "
                    "must belong to the same employee."
                )

            if lot.balance.organization_id != request.organization_id:
                errors["leave_request"] = (
                    "The leave request and carry-forward lot "
                    "must belong to the same organization."
                )

            if lot.balance.leave_type_id != request.leave_type_id:
                errors["leave_request"] = (
                    "The leave request and carry-forward lot "
                    "must use the same leave type."
                )

            if request.status != LeaveRequest.Status.APPROVED:
                errors["leave_request"] = (
                    "Only approved leave requests can consume "
                    "carry-forward days."
                )

            if not (
                lot.carried_forward_on
                <= self.consumed_on
                < lot.expires_on
            ):
                errors["consumed_on"] = (
                    "Consumption date must fall within "
                    "the carry-forward lot's validity period."
                )

            if not (
                request.start_date
                <= self.consumed_on
                <= request.end_date
            ):
                errors["consumed_on"] = (
                    "Consumption date must fall within "
                    "the leave request dates."
                )

        if self.allocated_days is not None and self.allocated_days <= 0:
            errors["allocated_days"] = (
                "Allocated days must be greater than zero."
            )

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise ValidationError(
                "Carry-forward consumption records are immutable."
            )
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError(
            "Carry-forward consumption records cannot be deleted."
        )

    def __str__(self):
        return (
            f"Lot {self.lot_id} - Request {self.leave_request_id} - "
            f"{self.consumed_on} - {self.allocated_days} days"
        )


class LeaveCarryForwardConsumptionReversal(models.Model):
    """
    An immutable event reversing a previous carry-forward
    consumption allocation.
    """

    consumption = models.OneToOneField(
        LeaveCarryForwardConsumption,
        on_delete=models.PROTECT,
        related_name="reversal",
    )
    reversed_days = models.DecimalField(
        max_digits=6,
        decimal_places=2,
    )
    reason = models.CharField(max_length=255)
    idempotency_key = models.CharField(
        max_length=255,
        unique=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at", "id"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(reversed_days__gt=0),
                name="carry_forward_reversal_positive",
            ),
        ]

    def clean(self):
        super().clean()
        errors = {}

        if self.consumption_id:
            if (
                self.reversed_days is not None
                and self.reversed_days != self.consumption.allocated_days
            ):
                errors["reversed_days"] = (
                    "A consumption reversal must reverse "
                    "the full original allocation."
                )

        if self.reversed_days is not None and self.reversed_days <= 0:
            errors["reversed_days"] = (
                "Reversed days must be greater than zero."
            )

        if not self.reason:
            errors["reason"] = "A reversal reason is required."

        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise ValidationError(
                "Carry-forward reversal records are immutable."
            )
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError(
            "Carry-forward reversal records cannot be deleted."
        )

    def __str__(self):
        return (
            f"Reversal of consumption {self.consumption_id} "
            f"({self.reversed_days} days)"
        )
