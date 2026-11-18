
from datetime import date
from types import SimpleNamespace

from django.contrib import admin
from django.forms.models import model_to_dict
from django.test import TestCase

from accounts.models import Organization
from employees.admin import EmployeeAdmin, EmployeeAdminForm
from employees.eligibility_services import (
    create_initial_employee_eligibility,
)
from employees.models import (
    Branch,
    Department,
    Designation,
    Employee,
    EmployeeEligibilityHistory,
)
from django.contrib.auth import get_user_model


User = get_user_model()


class EmployeeAdminEligibilityTests(TestCase):

    def setUp(self):
        self.organization = Organization.objects.create(
            name="Admin Test Organization",
            code="ADMINTEST",
        )

        self.admin_user = User.objects.create_user(
            username="employee_admin_test",
            password="TestOnly-Valid-123!",
        )

        self.department = Department.objects.create(
            name="Admin Test Department",
            code="ADMTEST",
        )

        self.new_department = Department.objects.create(
            name="Admin New Department",
            code="ADMNEW",
        )

        self.designation = Designation.objects.create(
            name="Admin Test Designation",
            code="ADM-DES",
        )

        self.branch = Branch.objects.create(
            name="Admin Test Branch",
            code="ADM-BR",
            state="Karnataka",
            city="Mysuru",
        )

        self.employee = Employee.objects.create(
            organization=self.organization,
            first_name="Test",
            last_name="Employee",
            official_email="admin.employee@example.com",
            registered_mobile="9876543210",
            joining_date=date(2025, 1, 1),
            probation_end_date=date(2025, 4, 1),
            employee_type="FULL_TIME",
            department=self.department,
            designation=self.designation,
            branch=self.branch,
            status=Employee.Status.ACTIVE,
        )

        create_initial_employee_eligibility(
            employee=self.employee,
            effective_from=self.employee.joining_date,
            changed_by=self.admin_user,
        )

        self.employee_admin = EmployeeAdmin(
            Employee,
            admin.site,
        )

    def get_form_data(self, employee, **overrides):
        data = model_to_dict(employee)
        data.update(overrides)
        return data

    def save_employee_form(self, data):
        form = EmployeeAdminForm(
            data=data,
            instance=self.employee,
        )

        self.assertTrue(form.is_valid(), form.errors)

        obj = form.save(commit=False)

        request = SimpleNamespace(
            user=self.admin_user,
        )

        self.employee_admin.save_model(
            request,
            obj,
            form,
            change=True,
        )

        self.employee.refresh_from_db()

    def test_department_change_creates_new_history(self):
        effective_from = date(2025, 2, 1)

        data = self.get_form_data(
            self.employee,
            department=self.new_department.pk,
            eligibility_effective_from=effective_from,
        )

        self.save_employee_form(data)

        history = EmployeeEligibilityHistory.objects.filter(
            employee=self.employee,
        ).order_by("effective_from")

        self.assertEqual(history.count(), 2)

        old_history = history[0]
        new_history = history[1]

        self.assertEqual(
            old_history.effective_until,
            date(2025, 1, 31),
        )

        self.assertEqual(
            new_history.department,
            self.new_department,
        )

        self.assertEqual(
            new_history.source,
            EmployeeEligibilityHistory.Source.ADMIN_UPDATE,
        )

    def test_employee_type_change_creates_new_history(self):
        effective_from = date(2025, 2, 1)

        data = self.get_form_data(
            self.employee,
            employee_type="INTERN",
            eligibility_effective_from=effective_from,
        )

        self.save_employee_form(data)

        history = EmployeeEligibilityHistory.objects.filter(
            employee=self.employee,
        ).order_by("effective_from")

        self.assertEqual(history.count(), 2)
        self.assertEqual(history[1].employee_type, "INTERN")

    def test_probation_date_change_creates_new_history(self):
        effective_from = date(2025, 2, 1)
        new_probation_end = date(2025, 5, 1)

        data = self.get_form_data(
            self.employee,
            probation_end_date=new_probation_end,
            eligibility_effective_from=effective_from,
        )

        self.save_employee_form(data)

        history = EmployeeEligibilityHistory.objects.filter(
            employee=self.employee,
        ).order_by("effective_from")

        self.assertEqual(history.count(), 2)

        self.assertEqual(
            history[1].probation_end_date,
            new_probation_end,
        )

    def test_invalid_effective_date_is_rejected(self):
        data = self.get_form_data(
            self.employee,
            department=self.new_department.pk,
            eligibility_effective_from=date(2025, 1, 1),
        )

        form = EmployeeAdminForm(
            data=data,
            instance=self.employee,
        )

        self.assertFalse(form.is_valid())

        self.assertIn(
            "eligibility_effective_from",
            form.errors,
        )

        self.assertEqual(
            EmployeeEligibilityHistory.objects.filter(
                employee=self.employee,
            ).count(),
            1,
        )

    def test_unrelated_employee_edit_does_not_create_history(self):
        data = self.get_form_data(
            self.employee,
            first_name="Updated",
        )

        self.save_employee_form(data)

        self.assertEqual(self.employee.first_name, "Updated")

        self.assertEqual(
            EmployeeEligibilityHistory.objects.filter(
                employee=self.employee,
            ).count(),
            1,
        )

    def test_admin_creation_creates_initial_history(self):
        new_employee = Employee(
            organization=self.organization,
            first_name="New",
            last_name="Employee",
            official_email="new.admin.employee@example.com",
            registered_mobile="9876543211",
            joining_date=date(2025, 3, 1),
            probation_end_date=date(2025, 6, 1),
            employee_type="FULL_TIME",
            department=self.department,
            designation=self.designation,
            branch=self.branch,
            status=Employee.Status.ACTIVE,
        )

        form = SimpleNamespace(
            cleaned_data={
                "eligibility_effective_from": None,
            }
        )

        request = SimpleNamespace(
            user=self.admin_user,
        )

        self.employee_admin.save_model(
            request,
            new_employee,
            form,
            change=False,
        )

        history = EmployeeEligibilityHistory.objects.get(
            employee=new_employee,
        )

        self.assertEqual(
            history.effective_from,
            new_employee.joining_date,
        )

        self.assertEqual(
            history.source,
            EmployeeEligibilityHistory.Source.EMPLOYEE_CREATION,
        )
