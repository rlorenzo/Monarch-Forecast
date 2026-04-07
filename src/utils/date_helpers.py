"""Date calculation utilities for forecasting."""

from datetime import date, timedelta
from typing import Generator


def date_range(start: date, end: date) -> Generator[date, None, None]:
    """Yield each date from start to end inclusive."""
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def next_occurrence(base_date: date, frequency: str, after: date) -> date | None:
    """Find the next occurrence of a recurring event on or after `after`.

    Args:
        base_date: A known occurrence date (anchor).
        frequency: One of "weekly", "biweekly", "monthly", "semimonthly", "yearly".
        after: Find the next occurrence on or after this date.

    Returns:
        The next occurrence date, or None if frequency is unrecognized.
    """
    if frequency == "weekly":
        days_ahead = (base_date.weekday() - after.weekday()) % 7
        candidate = after + timedelta(days=days_ahead)
        return candidate if candidate >= after else candidate + timedelta(weeks=1)

    if frequency == "biweekly":
        # Find how many weeks since base, snap to next even-week boundary
        delta_days = (after - base_date).days
        weeks_since = delta_days // 7
        if weeks_since % 2 != 0:
            weeks_since += 1
        candidate = base_date + timedelta(weeks=weeks_since)
        if candidate < after:
            candidate += timedelta(weeks=2)
        return candidate

    if frequency == "monthly":
        # Same day of month
        day = min(base_date.day, 28)  # safe day for all months
        candidate = after.replace(day=day)
        if candidate < after:
            month = candidate.month + 1
            year = candidate.year + (month - 1) // 12
            month = (month - 1) % 12 + 1
            candidate = candidate.replace(year=year, month=month, day=day)
        return candidate

    if frequency == "semimonthly":
        # Two payments per month: on base_date.day and 15 days later (capped at 28)
        day1 = min(base_date.day, 28)
        day2 = min(day1 + 15, 28)
        if day1 == day2:
            day1 = 1  # fallback to 1st and 16th if both land on 28
            day2 = 16
        candidates = []
        for d in (day1, day2):
            c = after.replace(day=d)
            if c < after:
                month = c.month + 1
                year = c.year + (month - 1) // 12
                month = (month - 1) % 12 + 1
                c = c.replace(year=year, month=month, day=d)
            candidates.append(c)
        return min(candidates)

    if frequency == "yearly":
        try:
            candidate = base_date.replace(year=after.year)
        except ValueError:
            # Feb 29 in a non-leap year: fall back to Feb 28
            candidate = base_date.replace(year=after.year, day=28)
        if candidate < after:
            try:
                candidate = base_date.replace(year=after.year + 1)
            except ValueError:
                candidate = base_date.replace(year=after.year + 1, day=28)
        return candidate

    return None


def occurrences_in_range(
    base_date: date, frequency: str, start: date, end: date
) -> list[date]:
    """Return all occurrences of a recurring event within [start, end]."""
    dates: list[date] = []
    current = next_occurrence(base_date, frequency, start)
    while current is not None and current <= end:
        dates.append(current)
        current = next_occurrence(base_date, frequency, current + timedelta(days=1))
    return dates
