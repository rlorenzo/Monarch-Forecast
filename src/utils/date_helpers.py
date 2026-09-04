"""Date calculation utilities for forecasting."""

from collections.abc import Generator
from datetime import date, timedelta


def date_range(start: date, end: date) -> Generator[date, None, None]:
    """Yield each date from start to end inclusive."""
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def add_months(year: int, month: int, k: int) -> tuple[int, int]:
    """Shift a (year, month) pair by k months."""
    total = (year * 12 + month - 1) + k
    return total // 12, total % 12 + 1


def _next_on_day(after: date, day: int) -> date:
    """First date on or after `after` whose day-of-month is `day` (<= 28)."""
    candidate = after.replace(day=day)
    if candidate < after:
        year, month = add_months(candidate.year, candidate.month, 1)
        candidate = candidate.replace(year=year, month=month)
    return candidate


def next_occurrence(base_date: date, frequency: str, after: date) -> date | None:
    """Find the next occurrence of a recurring event on or after `after`.

    Args:
        base_date: A known occurrence date (anchor).
        frequency: One of "weekly", "biweekly", "monthly", "semimonthly",
            "bimonthly", "quarterly", "semiannual", "yearly".
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
        # Same day of month, capped at 28 so it exists in every month.
        return _next_on_day(after, min(base_date.day, 28))

    if frequency in ("bimonthly", "quarterly", "semiannual"):
        # Month-stepped cycles anchored to the base date's month phase.
        # Day-of-month capped at 28 like the monthly branch.
        step = {"bimonthly": 2, "quarterly": 3, "semiannual": 6}[frequency]
        day = min(base_date.day, 28)
        months_ahead = (after.year - base_date.year) * 12 + (after.month - base_date.month)
        k = max(0, -(-months_ahead // step))  # ceil, floored at the anchor
        while True:
            year, month = add_months(base_date.year, base_date.month, k * step)
            candidate = date(year, month, day)
            if candidate >= after:
                return candidate
            k += 1

    if frequency == "semimonthly":
        # Two payments per month. The companion day sits 15 days from the
        # anchor in whichever direction stays inside the month: an anchor
        # on the 15th pairs with the 1st, not a nonsense 28th/30th.
        day1 = min(base_date.day, 28)
        day2 = day1 + 15 if day1 + 15 <= 28 else max(1, day1 - 15)
        return min(_next_on_day(after, d) for d in (day1, day2))

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


def occurrences_in_range(base_date: date, frequency: str, start: date, end: date) -> list[date]:
    """Return all occurrences of a recurring event within [start, end]."""
    dates: list[date] = []
    current = next_occurrence(base_date, frequency, start)
    while current is not None and current <= end:
        dates.append(current)
        current = next_occurrence(base_date, frequency, current + timedelta(days=1))
    return dates
