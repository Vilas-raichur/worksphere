from datetime import date
from types import SimpleNamespace

from django.test import SimpleTestCase

from leave_management.leave_periods import get_leave_year_period


class LeaveYearPeriodTests(SimpleTestCase):

    def make_organization(self, month, day):
        return SimpleNamespace(
            leave_year_start_month=month,
            leave_year_start_day=day,
        )

    def test_calendar_year(self):
        organization = self.make_organization(1, 1)

        result = get_leave_year_period(
            organization,
            date(2026, 11, 15),
        )

        self.assertEqual(
            result,
            (date(2026, 1, 1), date(2026, 12, 31)),
        )

    def test_financial_year(self):
        organization = self.make_organization(4, 1)

        result = get_leave_year_period(
            organization,
            date(2026, 11, 15),
        )

        self.assertEqual(
            result,
            (date(2026, 4, 1), date(2027, 3, 31)),
        )

    def test_date_before_leave_year_start(self):
        organization = self.make_organization(4, 1)

        result = get_leave_year_period(
            organization,
            date(2026, 2, 15),
        )

        self.assertEqual(
            result,
            (date(2025, 4, 1), date(2026, 3, 31)),
        )

    def test_custom_month_and_day(self):
        organization = self.make_organization(10, 15)

        result = get_leave_year_period(
            organization,
            date(2026, 11, 3),
        )

        self.assertEqual(
            result,
            (date(2026, 10, 15), date(2027, 10, 14)),
        )

    def test_february_29_clamps_in_non_leap_year(self):
        organization = self.make_organization(2, 29)

        result = get_leave_year_period(
            organization,
            date(2026, 3, 15),
        )

        self.assertEqual(
            result,
            (date(2026, 2, 28), date(2027, 2, 27)),
        )

    def test_february_29_uses_leap_day_in_leap_year(self):
        organization = self.make_organization(2, 29)

        result = get_leave_year_period(
            organization,
            date(2028, 3, 15),
        )

        self.assertEqual(
            result,
            (date(2028, 2, 29), date(2029, 2, 27)),
        )

    def test_configured_start_date_belongs_to_new_period(self):
        organization = self.make_organization(4, 1)

        result = get_leave_year_period(
            organization,
            date(2026, 4, 1),
        )

        self.assertEqual(
            result,
            (date(2026, 4, 1), date(2027, 3, 31)),
        )