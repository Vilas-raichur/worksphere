from types import SimpleNamespace
from unittest.mock import patch

from django.test import TestCase

from employees.models import Employee, EmployeeDocument

from attendance.services import (
    _validate_manager_assignment,
    _validate_manager_eligibility,
    approve_wfh_request,
    reject_wfh_request,
)
from attendance.models import WFHRequest


class ManagerEligibilityServiceTests(TestCase):
    def setUp(self):
        self.manager = SimpleNamespace(
            pk=25,
            organization_id=1,
            status=Employee.Status.ACTIVE,
            employee_id="WSMYS2026005",
            user_id=25,
            user=SimpleNamespace(is_active=True),
        )

        self.requirement = SimpleNamespace(
            id=1,
            code="GOV_ID",
        )

        self.verified_document = SimpleNamespace(
            document_requirement_id=1,
            status=EmployeeDocument.Status.VERIFIED,
        )

    def validate_with_mocked_documents(self, requirements, documents):
        with (
            patch("accounts.models.DocumentRequirement") as requirement_model,
            patch(
                "employees.models.EmployeeDocument.objects.filter",
                return_value=documents,
            ),
        ):
            requirement_model.objects.filter.return_value.order_by.return_value = (
                requirements
            )

            return _validate_manager_eligibility(
                self.manager,
                self.manager.organization_id,
            )

    def test_inactive_account_cannot_be_manager(self):
        self.manager.user.is_active = False

        with self.assertRaisesRegex(
            PermissionError,
            "active linked account",
        ):
            _validate_manager_eligibility(self.manager, 1)

    def test_missing_permanent_employee_id_is_rejected(self):
        self.manager.employee_id = None

        with self.assertRaisesRegex(
            PermissionError,
            "permanent Employee ID",
        ):
            _validate_manager_eligibility(self.manager, 1)

    def test_missing_document_configuration_fails_closed(self):
        with self.assertRaisesRegex(
            PermissionError,
            "no active required document rules",
        ):
            self.validate_with_mocked_documents([], [])

    def test_missing_required_document_is_rejected(self):
        with self.assertRaisesRegex(
            PermissionError,
            "GOV_ID",
        ):
            self.validate_with_mocked_documents(
                [self.requirement],
                [],
            )

    def test_fully_verified_manager_is_eligible(self):
        result = self.validate_with_mocked_documents(
            [self.requirement],
            [self.verified_document],
        )

        self.assertIs(result, self.manager)

    def test_wfh_assignment_rejects_ineligible_manager(self):
        self.validate_with_mocked_documents(
            [self.requirement],
            [],
        ) if False else None

        with (
            patch(
                "attendance.services._validate_manager_eligibility",
                side_effect=PermissionError("Documents are not verified."),
            ),
        ):
            employee_requesting_wfh = SimpleNamespace(
                organization_id=1,
                manager=self.manager,
            )

            with self.assertRaisesRegex(
                ValueError,
                "Assigned manager is not eligible",
            ):
                _validate_manager_assignment(employee_requesting_wfh)

    def test_wfh_approval_rejects_ineligible_reviewer(self):
        wfh_request = SimpleNamespace(
            employee=SimpleNamespace(organization_id=1),
            manager_at_request=object(),
            status=WFHRequest.Status.PENDING,
        )
        reviewer = object()

        with (
            patch(
                "attendance.services._is_assigned_manager",
                return_value=True,
            ),
            patch(
                "attendance.services._validate_manager_eligibility",
                side_effect=PermissionError("Manager is not eligible."),
            ),
        ):
            with self.assertRaisesRegex(
                PermissionError,
                "Manager is not eligible",
            ):
                approve_wfh_request(wfh_request, reviewer)

    def test_wfh_rejection_rejects_ineligible_reviewer(self):
        wfh_request = SimpleNamespace(
            employee=SimpleNamespace(organization_id=1),
            manager_at_request=object(),
            status=WFHRequest.Status.PENDING,
        )
        reviewer = object()

        with (
            patch(
                "attendance.services._is_assigned_manager",
                return_value=True,
            ),
            patch(
                "attendance.services._validate_manager_eligibility",
                side_effect=PermissionError("Manager is not eligible."),
            ),
        ):
            with self.assertRaisesRegex(
                PermissionError,
                "Manager is not eligible",
            ):
                reject_wfh_request(wfh_request, reviewer)