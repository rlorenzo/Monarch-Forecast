"""Tests for date calculation utilities."""

from datetime import date

from src.utils.date_helpers import date_range, next_occurrence, occurrences_in_range


class TestDateRange:
    def test_single_day(self):
        days = list(date_range(date(2026, 1, 1), date(2026, 1, 1)))
        assert days == [date(2026, 1, 1)]

    def test_multiple_days(self):
        days = list(date_range(date(2026, 1, 1), date(2026, 1, 3)))
        assert days == [date(2026, 1, 1), date(2026, 1, 2), date(2026, 1, 3)]

    def test_empty_range(self):
        days = list(date_range(date(2026, 1, 5), date(2026, 1, 1)))
        assert days == []


class TestNextOccurrenceWeekly:
    def test_same_day(self):
        # Base is a Wednesday, after is the same Wednesday
        base = date(2026, 1, 7)  # Wednesday
        result = next_occurrence(base, "weekly", date(2026, 1, 7))
        assert result == date(2026, 1, 7)

    def test_next_week(self):
        base = date(2026, 1, 7)  # Wednesday
        result = next_occurrence(base, "weekly", date(2026, 1, 8))
        assert result == date(2026, 1, 14)
        assert result.weekday() == base.weekday()


class TestNextOccurrenceBiweekly:
    def test_on_base_date(self):
        base = date(2026, 1, 3)
        result = next_occurrence(base, "biweekly", date(2026, 1, 3))
        assert result == date(2026, 1, 3)

    def test_next_biweekly(self):
        base = date(2026, 1, 3)
        result = next_occurrence(base, "biweekly", date(2026, 1, 4))
        assert result == date(2026, 1, 17)


class TestNextOccurrenceMonthly:
    def test_same_month(self):
        result = next_occurrence(date(2026, 1, 15), "monthly", date(2026, 1, 1))
        assert result == date(2026, 1, 15)

    def test_next_month(self):
        result = next_occurrence(date(2026, 1, 15), "monthly", date(2026, 1, 16))
        assert result == date(2026, 2, 15)

    def test_december_wraps_to_january(self):
        result = next_occurrence(date(2026, 1, 10), "monthly", date(2026, 12, 11))
        assert result == date(2027, 1, 10)

    def test_day_capped_at_28(self):
        # Base on the 31st gets capped to 28 for safety
        result = next_occurrence(date(2026, 1, 31), "monthly", date(2026, 2, 1))
        assert result.day == 28


class TestNextOccurrenceSemimonthly:
    def test_two_dates_per_month(self):
        base = date(2026, 1, 5)
        # Should produce two dates per month: 5th and 20th
        d1 = next_occurrence(base, "semimonthly", date(2026, 1, 1))
        assert d1 == date(2026, 1, 5)
        d2 = next_occurrence(base, "semimonthly", date(2026, 1, 6))
        assert d2 == date(2026, 1, 20)


class TestNextOccurrenceYearly:
    def test_same_year(self):
        result = next_occurrence(date(2026, 6, 15), "yearly", date(2026, 1, 1))
        assert result == date(2026, 6, 15)

    def test_next_year(self):
        result = next_occurrence(date(2026, 3, 1), "yearly", date(2026, 4, 1))
        assert result == date(2027, 3, 1)

    def test_leap_day_fallback(self):
        # Feb 29 base in a non-leap year
        result = next_occurrence(date(2024, 2, 29), "yearly", date(2025, 1, 1))
        assert result == date(2025, 2, 28)


class TestNextOccurrenceUnknown:
    def test_unknown_frequency(self):
        assert next_occurrence(date(2026, 1, 1), "quarterly", date(2026, 1, 1)) is None


class TestOccurrencesInRange:
    def test_weekly_in_month(self):
        dates = occurrences_in_range(
            date(2026, 1, 5),  # Monday
            "weekly",
            date(2026, 1, 1),
            date(2026, 1, 31),
        )
        assert len(dates) >= 4
        for d in dates:
            assert d.weekday() == date(2026, 1, 5).weekday()

    def test_monthly_in_quarter(self):
        dates = occurrences_in_range(
            date(2026, 1, 15),
            "monthly",
            date(2026, 1, 1),
            date(2026, 3, 31),
        )
        assert dates == [date(2026, 1, 15), date(2026, 2, 15), date(2026, 3, 15)]

    def test_empty_range(self):
        dates = occurrences_in_range(
            date(2026, 1, 15),
            "monthly",
            date(2026, 1, 16),
            date(2026, 2, 14),
        )
        assert dates == []
