"""Tests for credit card payment estimation."""

from datetime import date, timedelta

from src.data.credit_cards import _names_match, estimate_cc_payments
from src.forecast.models import RecurringItem


class TestNamesMatch:
    def test_matching_keywords(self):
        assert _names_match("chase sapphire", "chase sapphire payment") is True

    def test_partial_match(self):
        # 2 of 3 keywords match (chase, sapphire) → >= 50%
        assert _names_match("chase sapphire preferred", "chase sapphire card") is True

    def test_insufficient_partial_match(self):
        # 1 of 3 keywords match (chase) → < 50%
        assert _names_match("chase sapphire preferred", "chase credit card") is False

    def test_no_match(self):
        assert _names_match("chase sapphire", "amex gold payment") is False

    def test_short_words_excluded(self):
        # Words with length <= 2 are filtered out
        assert _names_match("cc", "cc payment") is False

    def test_empty_name(self):
        assert _names_match("", "something") is False


class TestEstimateCcPayments:
    def test_no_accounts(self):
        assert estimate_cc_payments([], []) == []

    def test_positive_balance_skipped(self):
        accounts = [{"name": "Visa", "balance": 100.0}]
        assert estimate_cc_payments(accounts, []) == []

    def test_zero_balance_skipped(self):
        accounts = [{"name": "Visa", "balance": 0.0}]
        assert estimate_cc_payments(accounts, []) == []

    def test_negative_balance_creates_payment(self):
        accounts = [{"name": "Chase Visa", "balance": -500.0}]
        payments = estimate_cc_payments(accounts, [])
        assert len(payments) == 1
        assert payments[0].amount == -500.0
        assert "Chase Visa" in payments[0].name
        assert payments[0].date == date.today() + timedelta(days=25)

    def test_recurring_payment_date_used(self):
        today = date.today()
        accounts = [{"name": "Chase Sapphire", "balance": -1000.0}]
        recurring = [
            RecurringItem(
                name="Chase Sapphire Payment",
                amount=-1000.0,
                frequency="monthly",
                base_date=today + timedelta(days=10),
                category="Credit Card",
            ),
        ]
        payments = estimate_cc_payments(accounts, recurring)
        assert len(payments) == 1
        # Should use the recurring payment date, not the default 25-day
        assert payments[0].date != today + timedelta(days=25)
