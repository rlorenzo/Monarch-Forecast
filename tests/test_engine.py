"""Tests for the forecast engine."""

from datetime import date

from src.data.models import ForecastTransaction, RecurringItem
from src.forecast.engine import build_forecast


class TestBuildForecast:
    def test_empty_forecast(self):
        result = build_forecast(
            starting_balance=5000.0, recurring_items=[], start_date=date(2026, 1, 1), days_out=7
        )
        assert len(result.days) == 7
        assert result.starting_balance == 5000.0
        assert result.ending_balance == 5000.0

    def test_single_recurring_expense(self):
        items = [
            RecurringItem(
                name="Netflix",
                amount=-15.99,
                frequency="monthly",
                base_date=date(2026, 1, 15),
            ),
        ]
        result = build_forecast(
            starting_balance=1000.0,
            recurring_items=items,
            start_date=date(2026, 1, 1),
            days_out=30,
        )
        # Netflix should appear on Jan 15
        jan15 = next(d for d in result.days if d.date == date(2026, 1, 15))
        assert len(jan15.transactions) == 1
        assert jan15.transactions[0].amount == -15.99
        assert jan15.transactions[0].is_recurring is True

    def test_one_off_transaction(self):
        one_offs = [
            ForecastTransaction(
                date=date(2026, 1, 10),
                name="Tax Refund",
                amount=2500.0,
            ),
        ]
        result = build_forecast(
            starting_balance=1000.0,
            recurring_items=[],
            one_off_transactions=one_offs,
            start_date=date(2026, 1, 1),
            days_out=15,
        )
        jan10 = next(d for d in result.days if d.date == date(2026, 1, 10))
        assert jan10.transactions[0].amount == 2500.0
        assert result.ending_balance == 3500.0

    def test_one_off_outside_range_excluded(self):
        one_offs = [
            ForecastTransaction(date=date(2026, 3, 1), name="Future", amount=100.0),
        ]
        result = build_forecast(
            starting_balance=1000.0,
            recurring_items=[],
            one_off_transactions=one_offs,
            start_date=date(2026, 1, 1),
            days_out=30,
        )
        assert result.ending_balance == 1000.0

    def test_balance_accumulates(self):
        items = [
            RecurringItem(
                name="Pay", amount=1000.0, frequency="weekly", base_date=date(2026, 1, 5)
            ),
        ]
        result = build_forecast(
            starting_balance=0.0,
            recurring_items=items,
            start_date=date(2026, 1, 1),
            days_out=14,
        )
        assert result.ending_balance > 0
        assert result.total_income > 0

    def test_shortfall_detection(self):
        items = [
            RecurringItem(
                name="Rent", amount=-3000.0, frequency="monthly", base_date=date(2026, 1, 1)
            ),
        ]
        result = build_forecast(
            starting_balance=1000.0,
            recurring_items=items,
            start_date=date(2026, 1, 1),
            days_out=5,
            safety_threshold=0.0,
        )
        assert result.has_shortfall
        assert result.lowest_balance == -2000.0
