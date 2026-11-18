
from datetime import date
from types import SimpleNamespace

from django.test import SimpleTestCase

from leave_management.leave_periods import (
    get_carry_forward_interval,
    get_completed_carry_forward_intervals,
)


class CarryForwardPeriodTests(SimpleTestCase):

    def setUp(self):
        self.organization = SimpleNamespace(
            leave_year_start_month=4,
            leave_year_start_day=15,
        )

    def test_quarterly_interval_uses_organization_leave_year(self):
        start, end = get_carry_forward_interval(
            self.organization,
            date(2026, 6, 30),
            3,
        )

        self.assertEqual(start, date(2026, 4, 15))
        self.assertEqual(end, date(2026, 7, 14))

    def test_exact_interval_boundary_starts_next_interval(self):
        start, end = get_carry_forward_interval(
            self.organization,
            date(2026, 7, 15),
            3,
        )

        self.assertEqual(start, date(2026, 7, 15))
        self.assertEqual(end, date(2026, 10, 14))

    def test_two_month_interval(self):
        start, end = get_carry_forward_interval(
            self.organization,
            date(2026, 6, 1),
            2,
        )

        self.assertEqual(start, date(2026, 4, 15))
        self.assertEqual(end, date(2026, 6, 14))

    def test_completed_quarter_is_returned_on_boundary_date(self):
        intervals = get_completed_carry_forward_intervals(
            self.organization,
            date(2026, 7, 15),
            3,
        )

        self.assertEqual(
            intervals,
            [
                (date(2026, 4, 15), date(2026, 7, 14)),
            ],
        )

    def test_incomplete_interval_is_not_returned(self):
        intervals = get_completed_carry_forward_intervals(
            self.organization,
            date(2026, 7, 10),
            3,
        )

        self.assertEqual(intervals, [])

    def test_multiple_completed_quarters(self):
        intervals = get_completed_carry_forward_intervals(
            self.organization,
            date(2027, 1, 15),
            3,
        )

        self.assertEqual(
            intervals,
            [
                (date(2026, 4, 15), date(2026, 7, 14)),
                (date(2026, 7, 15), date(2026, 10, 14)),
                (date(2026, 10, 15), date(2027, 1, 14)),
            ],
        )

    def test_previous_leave_year_final_interval_is_included(self):
        intervals = get_completed_carry_forward_intervals(
            self.organization,
            date(2027, 4, 15),
            3,
        )

        self.assertEqual(
            intervals,
            [
                (date(2026, 4, 15), date(2026, 7, 14)),
                (date(2026, 7, 15), date(2026, 10, 14)),
                (date(2026, 10, 15), date(2027, 1, 14)),
                (date(2027, 1, 15), date(2027, 4, 14)),
            ],
        )

    def test_annual_interval_completes_at_next_leave_year(self):
        intervals = get_completed_carry_forward_intervals(
            self.organization,
            date(2027, 4, 15),
            12,
        )

        self.assertEqual(
            intervals,
            [
                (date(2026, 4, 15), date(2027, 4, 14)),
            ],
        )

    def test_unsupported_interval_is_rejected(self):
        with self.assertRaises(ValueError):
            get_carry_forward_interval(
                self.organization,
                date(2026, 6, 1),
                5,
            )
