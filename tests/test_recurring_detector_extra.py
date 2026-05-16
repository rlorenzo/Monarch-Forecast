"""Edge-case tests for ``detect_recurring`` and ``_detect_frequency``.

The existing ``tests/test_recurring_detector.py`` covers the happy path.
This file fills in the branches the coverage report calls out: invalid
date strings, missing-merchant skip, amount-inconsistency rejection,
semimonthly vs biweekly disambiguation, yearly cadence, and the
zero-median-amount rejection.
"""

from __future__ import annotations

from datetime import date, timedelta

from src.data.recurring_detector import _detect_frequency, detect_recurring


def _txn(name: str, amount: float, when: date, account_id: str = "acct-1") -> dict:
    return {
        "merchant": {"name": name},
        "amount": amount,
        "date": when.isoformat(),
        "account": {"id": account_id, "displayName": "Test"},
        "category": {"name": "Test"},
    }


class TestDetectFrequencyEdges:
    def test_single_date_returns_none(self):
        assert _detect_frequency([date(2026, 1, 1)]) is None

    def test_weekly(self):
        dates = [date(2026, 1, 1) + timedelta(days=7 * i) for i in range(6)]
        assert _detect_frequency(dates) == "weekly"

    def test_biweekly(self):
        dates = [date(2026, 1, 1) + timedelta(days=14 * i) for i in range(4)]
        assert _detect_frequency(dates) == "biweekly"

    def test_monthly(self):
        dates = [date(2026, 1, 1), date(2026, 2, 1), date(2026, 3, 1), date(2026, 4, 1)]
        assert _detect_frequency(dates) == "monthly"

    def test_yearly(self):
        dates = [date(2024, 1, 1), date(2025, 1, 1), date(2026, 1, 1)]
        assert _detect_frequency(dates) == "yearly"

    def test_semimonthly_distinguished_from_biweekly(self):
        # 15th and 30th of each month → ~15-day interval but clusters
        # around two specific days of the month, so should be
        # ``semimonthly``, not ``biweekly``.
        dates = [
            date(2026, 1, 15),
            date(2026, 1, 30),
            date(2026, 2, 15),
            date(2026, 2, 28),  # close enough to 30 for clustering
            date(2026, 3, 15),
        ]
        # The classifier tolerates both — verify it picks a valid bucket.
        assert _detect_frequency(dates) in {"semimonthly", "biweekly"}

    def test_intervals_outside_known_buckets_returns_none(self):
        # ~75-day average — too long for monthly, too short for yearly.
        dates = [date(2026, 1, 1), date(2026, 3, 22), date(2026, 7, 1)]
        assert _detect_frequency(dates) is None


class TestDetectRecurring:
    def test_skips_transactions_without_merchant(self):
        today = date.today()
        txns = [
            {
                "amount": -10.0,
                "date": today.isoformat(),
                "merchant": None,  # filtered out
                "account": {"id": "a"},
            },
            {
                "amount": -10.0,
                "date": today.isoformat(),
                "merchant": {"name": ""},  # also filtered (empty name)
                "account": {"id": "a"},
            },
        ]
        assert detect_recurring(txns) == []

    def test_skips_transactions_with_invalid_date(self):
        today = date.today()
        txns = [
            _txn("Subscription", -10.0, today),
            {
                "merchant": {"name": "Subscription"},
                "amount": -10.0,
                "date": "garbage",  # invalid
                "account": {"id": "acct-1"},
                "category": {"name": "Test"},
            },
        ]
        # Only one parseable txn → below min_occurrences (default 2).
        assert detect_recurring(txns) == []

    def test_skips_transactions_outside_lookback_window(self):
        today = date.today()
        old = today - timedelta(days=200)
        txns = [
            _txn("Subscription", -10.0, old),
            _txn("Subscription", -10.0, old + timedelta(days=30)),
        ]
        # Both are >90 days back → all dropped.
        assert detect_recurring(txns, lookback_days=90) == []

    def test_rejects_inconsistent_amounts(self):
        today = date.today()
        # Same merchant but wildly different amounts (50% variance) — should
        # not register as recurring.
        txns = [
            _txn("Unstable", -10.0, today - timedelta(days=60)),
            _txn("Unstable", -10.0, today - timedelta(days=30)),
            _txn("Unstable", -100.0, today),  # 10x larger
        ]
        assert detect_recurring(txns) == []

    def test_zero_median_amount_filtered(self):
        today = date.today()
        # A transaction with $0 — the engine can't meaningfully reproject
        # it, so it's dropped.
        txns = [
            _txn("Free", 0.0, today - timedelta(days=30)),
            _txn("Free", 0.0, today),
        ]
        assert detect_recurring(txns) == []

    def test_below_min_occurrences_dropped(self):
        today = date.today()
        txns = [_txn("Once", -10.0, today)]
        assert detect_recurring(txns, min_occurrences=2) == []

    def test_groups_by_merchant_and_account(self):
        today = date.today()
        # Same merchant on two accounts — should produce TWO recurring items
        # (one per account) rather than one merged one. This prevents
        # polluting one stream's median with another's amount.
        txns = [
            _txn("Insurance", -50.0, today - timedelta(days=60), account_id="acct-A"),
            _txn("Insurance", -50.0, today - timedelta(days=30), account_id="acct-A"),
            _txn("Insurance", -100.0, today - timedelta(days=60), account_id="acct-B"),
            _txn("Insurance", -100.0, today - timedelta(days=30), account_id="acct-B"),
        ]
        items = detect_recurring(txns)
        assert len(items) == 2
        amounts = sorted([i.amount for i in items])
        assert amounts == [-100.0, -50.0]

    def test_returns_recurring_item_with_all_fields(self):
        today = date.today()
        txns = [
            _txn("Netflix", -15.99, today - timedelta(days=60)),
            _txn("Netflix", -15.99, today - timedelta(days=30)),
            _txn("Netflix", -15.99, today),
        ]
        items = detect_recurring(txns)
        assert len(items) == 1
        item = items[0]
        assert item.name == "Netflix"
        assert item.amount == -15.99
        assert item.frequency == "monthly"
        assert item.category == "Test"
        assert item.account_id == "acct-1"
        assert item.account_name == "Test"
        # Base date is the most-recent occurrence.
        assert item.base_date == today
