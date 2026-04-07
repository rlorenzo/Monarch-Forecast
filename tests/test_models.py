"""Tests for forecast models."""

from datetime import date

from src.forecast.models import (
    ForecastDay,
    ForecastResult,
    ForecastTransaction,
    RecurringItem,
    TransactionType,
)


class TestRecurringItem:
    def test_create(self):
        item = RecurringItem(
            name="Netflix",
            amount=-15.99,
            frequency="monthly",
            base_date=date(2026, 1, 15),
            category="Subscriptions",
        )
        assert item.name == "Netflix"
        assert item.amount == -15.99
        assert item.frequency == "monthly"

    def test_defaults(self):
        item = RecurringItem(
            name="Paycheck",
            amount=3000.0,
            frequency="biweekly",
            base_date=date(2026, 1, 1),
        )
        assert item.account_id == ""
        assert item.is_credit_card_payment is False

    def test_transaction_type_income(self):
        item = RecurringItem(
            name="Paycheck", amount=3000.0, frequency="biweekly", base_date=date(2026, 1, 1)
        )
        assert item.transaction_type == TransactionType.INCOME

    def test_transaction_type_expense(self):
        item = RecurringItem(
            name="Rent", amount=-1500.0, frequency="monthly", base_date=date(2026, 2, 1)
        )
        assert item.transaction_type == TransactionType.EXPENSE


class TestForecastDay:
    def test_net_change(self):
        txns = [
            ForecastTransaction(date=date(2026, 1, 10), name="Pay", amount=3000.0),
            ForecastTransaction(date=date(2026, 1, 10), name="Rent", amount=-1500.0),
        ]
        day = ForecastDay(date=date(2026, 1, 10), starting_balance=5000.0, transactions=txns)
        assert day.net_change == 1500.0
        assert day.ending_balance == 6500.0

    def test_empty_day(self):
        day = ForecastDay(date=date(2026, 1, 10), starting_balance=5000.0)
        assert day.net_change == 0.0
        assert day.ending_balance == 5000.0


class TestForecastResult:
    def test_empty_forecast(self):
        result = ForecastResult(days=[], starting_balance=5000.0, safety_threshold=500.0)
        assert result.lowest_balance == 5000.0
        assert result.lowest_balance_date is None
        assert result.ending_balance == 5000.0
        assert result.has_shortfall is False

    def test_shortfall_detection(self):
        days = [
            ForecastDay(
                date=date(2026, 1, 1),
                starting_balance=1000.0,
                transactions=[
                    ForecastTransaction(date=date(2026, 1, 1), name="Rent", amount=-800.0)
                ],
            ),
        ]
        result = ForecastResult(days=days, starting_balance=1000.0, safety_threshold=500.0)
        assert result.has_shortfall is True
        assert date(2026, 1, 1) in result.shortfall_dates

    def test_income_and_expenses(self):
        days = [
            ForecastDay(
                date=date(2026, 1, 1),
                starting_balance=5000.0,
                transactions=[
                    ForecastTransaction(date=date(2026, 1, 1), name="Pay", amount=3000.0),
                    ForecastTransaction(date=date(2026, 1, 1), name="Rent", amount=-1500.0),
                ],
            ),
        ]
        result = ForecastResult(days=days, starting_balance=5000.0)
        assert result.total_income == 3000.0
        assert result.total_expenses == -1500.0
