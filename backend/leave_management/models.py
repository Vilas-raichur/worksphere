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
    entitled_days = models.PositiveSmallIntegerField()

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
        ]

    def clean(self):
        super().clean()

        errors = {}

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
