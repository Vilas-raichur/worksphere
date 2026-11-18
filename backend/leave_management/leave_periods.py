import calendar
from datetime import date, timedelta


def _make_leave_year_start(year, month, day):
    last_day = calendar.monthrange(year, month)[1]
    actual_day = min(day, last_day)

    return date(year, month, actual_day)


def get_leave_year_period(organization, reference_date):
    """
    Return the leave-year start and end dates containing reference_date.

    The configured start month and day define recurring annual periods.
    If the configured day does not exist in a particular year,
    the last day of that month is used.
    """
    month = organization.leave_year_start_month
    day = organization.leave_year_start_day

    current_year_start = _make_leave_year_start(
        reference_date.year,
        month,
        day,
    )

    if reference_date >= current_year_start:
        period_start = current_year_start
        next_period_start = _make_leave_year_start(
            reference_date.year + 1,
            month,
            day,
        )
    else:
        period_start = _make_leave_year_start(
            reference_date.year - 1,
            month,
            day,
        )
        next_period_start = current_year_start

    period_end = next_period_start - timedelta(days=1)

    return period_start, period_end



import calendar
from datetime import date, timedelta


SUPPORTED_CARRY_FORWARD_INTERVALS = (1, 2, 3, 4, 6, 12)


def _add_months_from_anchor(
    anchor_date,
    months,
):
    """
    Add months while preserving the original anchor day.

    Example:
        January 31 + 1 month  = February 28/29
        January 31 + 2 months = March 31

    The original anchor day is retained to avoid date drift.
    """
    absolute_month = (
        anchor_date.year * 12
        + anchor_date.month - 1
        + months
    )

    year = absolute_month // 12
    month = absolute_month % 12 + 1

    last_day = calendar.monthrange(year, month)[1]
    actual_day = min(anchor_date.day, last_day)

    return date(year, month, actual_day)


def get_carry_forward_interval(
    organization,
    reference_date,
    interval_months,
):
    """
    Return the carry-forward interval containing reference_date.

    The interval is aligned to the organization's leave-year start.

    Returns:
        (interval_start, interval_end)
    """
    if interval_months not in SUPPORTED_CARRY_FORWARD_INTERVALS:
        raise ValueError(
            "Unsupported carry-forward interval. "
            "Allowed values are 1, 2, 3, 4, 6 and 12."
        )

    leave_year_start, leave_year_end = get_leave_year_period(
        organization,
        reference_date,
    )

    elapsed_days = (reference_date - leave_year_start).days

    # Find the interval by comparing actual anchored boundaries.
    interval_number = 0

    while True:
        next_boundary = _add_months_from_anchor(
            leave_year_start,
            (interval_number + 1) * interval_months,
        )

        if reference_date < next_boundary:
            break

        interval_number += 1

    interval_start = _add_months_from_anchor(
        leave_year_start,
        interval_number * interval_months,
    )

    next_interval_start = _add_months_from_anchor(
        leave_year_start,
        (interval_number + 1) * interval_months,
    )

    interval_end = min(
        next_interval_start - timedelta(days=1),
        leave_year_end,
    )

    return interval_start, interval_end



def get_completed_carry_forward_intervals(
    organization,
    processing_date,
    interval_months,
):
    """
    Return completed carry-forward intervals up to processing_date.

    The previous leave year is included when processing_date is
    the first day of a new leave year.

    An interval is completed when its final date is earlier
    than processing_date.
    """
    if interval_months not in SUPPORTED_CARRY_FORWARD_INTERVALS:
        raise ValueError(
            "Unsupported carry-forward interval. "
            "Allowed values are 1, 2, 3, 4, 6 and 12."
        )

    completed_through = processing_date - timedelta(days=1)

    leave_year_start, leave_year_end = get_leave_year_period(
        organization,
        completed_through,
    )

    completed_intervals = []
    interval_number = 0

    while True:
        interval_start = _add_months_from_anchor(
            leave_year_start,
            interval_number * interval_months,
        )

        if interval_start > leave_year_end:
            break

        next_interval_start = _add_months_from_anchor(
            leave_year_start,
            (interval_number + 1) * interval_months,
        )

        interval_end = min(
            next_interval_start - timedelta(days=1),
            leave_year_end,
        )

        if interval_end > completed_through:
            break

        completed_intervals.append(
            (interval_start, interval_end)
        )

        interval_number += 1

    return completed_intervals
