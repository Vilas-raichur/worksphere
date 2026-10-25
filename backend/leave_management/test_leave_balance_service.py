from datetime import date
from unittest.mock import patch

from django.test import TestCase

from django.contrib.auth import get_user_model

from accounts.models import Organization
from employees.models import Branch, Department, Designation, Employee
from leave_management.models import LeaveBalance, LeaveRequest, LeaveType
from leave_management.services import get_employee_leave_balance_summary


class LeaveBalanceServiceTests(TestCase):
    def setUp(self):
        self.organization = Organization.objects.create(
            name="Leave Balance Service Organization",
            code="LBSORG",
        )

        self.department = Department.objects.create(
            name="Leave Balance Service Department",
            code="LBSDEP",
        )

        self.designation = Designation.objects.create(
            name="Leave Balance Service Designation",
            code="LBSDES",
        )

        self.branch = Branch.objects.create(
            name="Leave Balance Service Branch",
            code="LBSBR",
            state="Karnataka",
            city="Bengaluru",
        )

        self.employee = self.create_employee("001")
        self.manager = self.create_employee("002")

        self.leave_type = LeaveType.objects.create(
            organization=self.organization,
            code="ANNUAL",
            name="Annual Leave",
        )

        self.balance = LeaveBalance.objects.create(
            organization=self.organization,
            employee=self.employee,
            leave_type=self.leave_type,
            period_start=date(2026, 1, 1),
            period_end=date(2026, 12, 31),
            entitled_days=12,
        )

    def create_employee(self, suffix):
        user_model = get_user_model()
        login_identifier = (
            f"leave.balance.service.{suffix}@example.com"
        )

        user_kwargs = {
            user_model.USERNAME_FIELD: login_identifier,
        }

        # Populate the email field too when it is separate
        # from the user's username field.
        if (
            user_model.USERNAME_FIELD != "email"
            and any(
                field.name == "email"
                for field in user_model._meta.fields
            )
        ):
            user_kwargs["email"] = login_identifier

        user = user_model.objects.create_user(
            password="TestPassword123!",
            is_active=True,
            **user_kwargs,
        )

        return Employee.objects.create(
            employee_id=f"LBS-{suffix}",
            onboarding_reference=f"ONB-LBS-{suffix}",
            organization=self.organization,
            user=user,
            first_name="Test",
            last_name=f"Employee {suffix}",
            official_email=login_identifier,
            registered_mobile=f"9876543{suffix}",
            joining_date=date(2026, 1, 1),
            employee_type="FULL_TIME",
            department=self.department,
            designation=self.designation,
            branch=self.branch,
            status=Employee.Status.ACTIVE,
        )

    def create_leave_request(
        self,
        *,
        status,
        start_date=date(2026, 3, 2),
        end_date=date(2026, 3, 4),
        working_days_count=3,
        leave_type=None,
    ):
        return LeaveRequest.objects.create(
            organization=self.organization,
            employee=self.employee,
            leave_type=leave_type or self.leave_type,
            department_id_snapshot=self.employee.department_id,
            designation_id_snapshot=self.employee.designation_id,
            manager_at_request=self.manager,
            start_date=start_date,
            end_date=end_date,
            working_days_count=working_days_count,
            reason="Service test",
            status=status,
        )

    def test_balance_without_approved_leave(self):
        result = get_employee_leave_balance_summary(
            self.employee,
            as_of_date=date(2026, 6, 1),
        )

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["entitled_days"], 12)
        self.assertEqual(result[0]["used_days"], 0)
        self.assertEqual(result[0]["remaining_days"], 12)

    def test_approved_leave_reduces_remaining_balance(self):
        self.create_leave_request(
            status=LeaveRequest.Status.APPROVED,
            working_days_count=3,
        )

        result = get_employee_leave_balance_summary(
            self.employee,
            as_of_date=date(2026, 6, 1),
        )

        self.assertEqual(result[0]["used_days"], 3)
        self.assertEqual(result[0]["remaining_days"], 9)

    def test_pending_leave_does_not_reduce_balance(self):
        self.create_leave_request(
            status=LeaveRequest.Status.PENDING,
            working_days_count=3,
        )

        result = get_employee_leave_balance_summary(
            self.employee,
            as_of_date=date(2026, 6, 1),
        )

        self.assertEqual(result[0]["used_days"], 0)
        self.assertEqual(result[0]["remaining_days"], 12)

    def test_cross_period_request_counts_only_dates_inside_period(self):
        self.create_leave_request(
            status=LeaveRequest.Status.APPROVED,
            start_date=date(2026, 12, 30),
            end_date=date(2027, 1, 3),
            working_days_count=3,
        )

        with (
            patch(
                "leave_management.services.get_attendance_policy",
                return_value=object(),
            ),
            patch(
                "leave_management.services._working_dates",
                return_value=[
                    date(2026, 12, 30),
                    date(2026, 12, 31),
                ],
            ) as working_dates_mock,
        ):
            result = get_employee_leave_balance_summary(
                self.employee,
                as_of_date=date(2026, 12, 31),
            )

        self.assertEqual(result[0]["used_days"], 2)
        self.assertEqual(result[0]["remaining_days"], 10)

        working_dates_mock.assert_called_once_with(
            self.employee,
            working_dates_mock.call_args.args[1],
            date(2026, 12, 30),
            date(2026, 12, 31),
        )