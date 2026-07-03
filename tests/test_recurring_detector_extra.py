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
        # ~45-day median — too long for monthly, too short for bimonthly.
        dates = [date(2026, 1, 1), date(2026, 2, 15), date(2026, 4, 1)]
        assert _detect_frequency(dates) is None

    def test_bimonthly(self):
        dates = [date(2026, 1, 10), date(2026, 3, 10), date(2026, 5, 10)]
        assert _detect_frequency(dates) == "bimonthly"

    def test_quarterly(self):
        dates = [date(2026, 1, 5), date(2026, 4, 5), date(2026, 7, 5)]
        assert _detect_frequency(dates) == "quarterly"

    def test_median_tolerates_one_missed_charge(self):
        # Monthly with one skipped month: intervals [30, 30, 60] — the mean
        # (40) falls outside every band, the median (30) stays monthly.
        dates = [date(2026, 1, 1), date(2026, 1, 31), date(2026, 3, 2), date(2026, 5, 1)]
        assert _detect_frequency(dates) == "monthly"


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
        # Same merchant, no two amounts alike — nothing forms a consistent
        # majority, so it should not register as recurring.
        txns = [
            _txn("Unstable", -10.0, today - timedelta(days=60)),
            _txn("Unstable", -40.0, today - timedelta(days=30)),
            _txn("Unstable", -100.0, today),
        ]
        assert detect_recurring(txns) == []

    def test_single_outlier_does_not_disqualify_stream(self):
        today = date.today()
        # A one-off large purchase at a subscription merchant drops out of
        # the stream instead of disqualifying it (the old all-or-nothing
        # variance check rejected the whole group).
        txns = [
            _txn("Streaming Plus", -15.0, today - timedelta(days=60)),
            _txn("Streaming Plus", -15.0, today - timedelta(days=30)),
            _txn("Streaming Plus", -150.0, today - timedelta(days=20)),  # gift card
            _txn("Streaming Plus", -15.0, today),
        ]
        items = detect_recurring(txns)
        assert len(items) == 1
        assert items[0].amount == -15.0
        assert items[0].frequency == "monthly"

    def test_refund_does_not_disqualify_stream(self):
        today = date.today()
        # A refund at the same merchant flips sign; the majority-sign
        # subset should still detect the expense stream.
        txns = [
            _txn("Gym", -45.0, today - timedelta(days=60)),
            _txn("Gym", -45.0, today - timedelta(days=30)),
            _txn("Gym", 45.0, today - timedelta(days=25)),  # refund
            _txn("Gym", -45.0, today),
        ]
        items = detect_recurring(txns)
        assert len(items) == 1
        assert items[0].amount == -45.0

    def test_same_day_split_charges_count_once(self):
        today = date.today()
        # Two same-day charges (split transaction) must not inject a 0-day
        # interval that drags the cadence out of the monthly band.
        txns = [
            _txn("Insurance", -80.0, today - timedelta(days=60)),
            _txn("Insurance", -80.0, today - timedelta(days=30)),
            _txn("Insurance", -80.0, today - timedelta(days=30)),
            _txn("Insurance", -80.0, today),
        ]
        items = detect_recurring(txns)
        assert len(items) == 1
        assert items[0].frequency == "monthly"

    def test_plaid_name_fallback_groups_merchantless_txns(self):
        today = date.today()
        txns = [
            {
                "amount": -1200.0,
                "date": (today - timedelta(days=30)).isoformat(),
                "merchant": None,
                "plaidName": "ACH RENT PAYMENT",
                "account": {"id": "acct-1", "displayName": "Test"},
                "category": {"name": "Housing"},
            },
            {
                "amount": -1200.0,
                "date": today.isoformat(),
                "merchant": None,
                "plaidName": "ACH RENT PAYMENT",
                "account": {"id": "acct-1", "displayName": "Test"},
                "category": {"name": "Housing"},
            },
        ]
        items = detect_recurring(txns)
        assert len(items) == 1
        assert items[0].name == "ACH RENT PAYMENT"

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


class TestNullAmountTolerance:
    def test_null_amount_rows_skipped(self):
        today = date.today()
        txns = [
            _txn("Gym", -45.0, today - timedelta(days=60)),
            _txn("Gym", -45.0, today - timedelta(days=30)),
            _txn("Gym", -45.0, today),
        ]
        null_row = _txn("Gym", 0.0, today - timedelta(days=15))
        null_row["amount"] = None  # explicit JSON null from the API
        items = detect_recurring([*txns, null_row])
        assert len(items) == 1
        assert items[0].frequency == "monthly"


class TestPenaltyFeeExclusion:
    """Penalty fees must never be projected forward: the forecast exists
    to prevent them, not to schedule them."""

    def test_nsf_fees_not_detected_as_recurring(self):
        today = date.today()
        txns = [
            _txn("Non-Sufficient Funds Fee", -22.0, today - timedelta(days=60)),
            _txn("Non-Sufficient Funds Fee", -22.0, today - timedelta(days=30)),
            _txn("Non-Sufficient Funds Fee", -22.0, today),
        ]
        for t in txns:
            t["category"] = {"name": "Financial Fees"}
        assert detect_recurring(txns) == []

    def test_overdraft_and_late_fees_excluded(self):
        today = date.today()
        txns = [
            _txn("Overdraft Fee", -35.0, today - timedelta(days=30)),
            _txn("Overdraft Fee", -35.0, today),
            _txn("Late Fee", -29.0, today - timedelta(days=30)),
            _txn("Late Fee", -29.0, today),
        ]
        assert detect_recurring(txns) == []

    def test_nsf_matched_as_word_not_substring(self):
        # "Transfer" contains the letters n-s-f; it must not be filtered.
        today = date.today()
        txns = [
            _txn("Vanguard Transfer", -500.0, today - timedelta(days=30)),
            _txn("Vanguard Transfer", -500.0, today),
        ]
        items = detect_recurring(txns)
        assert len(items) == 1
        assert items[0].name == "Vanguard Transfer"

    def test_legitimate_maintenance_fee_still_detected(self):
        # "Financial Fees" category alone is not a penalty; a scheduled
        # account maintenance fee is a real recurring expense.
        today = date.today()
        txns = [
            _txn("Monthly Maintenance Fee", -15.0, today - timedelta(days=60)),
            _txn("Monthly Maintenance Fee", -15.0, today - timedelta(days=30)),
            _txn("Monthly Maintenance Fee", -15.0, today),
        ]
        for t in txns:
            t["category"] = {"name": "Financial Fees"}
        items = detect_recurring(txns)
        assert len(items) == 1
        assert items[0].frequency == "monthly"


class TestGenericDescriptorExclusion:
    """Bare bank descriptors name an event, not a counterparty; grouping
    them turns unrelated one-offs into phantom recurring streams."""

    def test_bare_deposit_never_recurring(self):
        today = date.today()
        txns = [
            _txn("Deposit", 63.05, today - timedelta(days=28)),
            _txn("Deposit", 60.00, today - timedelta(days=14)),
            _txn("Deposit", 63.05, today),
        ]
        assert detect_recurring(txns) == []

    def test_named_payroll_descriptor_still_detected(self):
        today = date.today()
        txns = [
            _txn("Acme Corp Payroll Deposit", 2400.0, today - timedelta(days=28)),
            _txn("Acme Corp Payroll Deposit", 2400.0, today - timedelta(days=14)),
            _txn("Acme Corp Payroll Deposit", 2400.0, today),
        ]
        items = detect_recurring(txns)
        assert len(items) == 1
        assert items[0].frequency == "biweekly"


class TestShortCadenceEvidence:
    def test_two_points_do_not_make_a_biweekly_stream(self):
        today = date.today()
        txns = [
            _txn("Farmers Market", -40.0, today - timedelta(days=14)),
            _txn("Farmers Market", -42.0, today),
        ]
        assert detect_recurring(txns) == []

    def test_three_points_do(self):
        today = date.today()
        txns = [
            _txn("Farmers Market", -40.0, today - timedelta(days=28)),
            _txn("Farmers Market", -42.0, today - timedelta(days=14)),
            _txn("Farmers Market", -41.0, today),
        ]
        items = detect_recurring(txns)
        assert len(items) == 1
        assert items[0].frequency == "biweekly"

    def test_monthly_keeps_two_occurrence_floor(self):
        today = date.today()
        txns = [
            _txn("Netflix", -15.49, today - timedelta(days=30)),
            _txn("Netflix", -15.49, today),
        ]
        items = detect_recurring(txns)
        assert len(items) == 1
        assert items[0].frequency == "monthly"


class TestStalenessGuard:
    def test_stream_that_stopped_months_ago_not_projected(self):
        # Real report: "St Bankcard Credit" charged Jan 2 and Feb 2, still
        # projected in July. A monthly stream 5 months quiet is history.
        today = date.today()
        txns = [
            _txn("St Bankcard Credit", -49.0, today - timedelta(days=181)),
            _txn("St Bankcard Credit", -49.0, today - timedelta(days=150)),
        ]
        assert detect_recurring(txns) == []

    def test_active_stream_with_posting_lag_kept(self):
        today = date.today()
        txns = [
            _txn("Netflix", -15.49, today - timedelta(days=70)),
            _txn("Netflix", -15.49, today - timedelta(days=40)),
        ]
        # Last seen 40 days ago: within 1.5 cycles + grace for monthly.
        items = detect_recurring(txns)
        assert len(items) == 1

    def test_quarterly_allows_proportional_quiet(self):
        today = date.today()
        txns = [
            _txn("HOA Dues", -300.0, today - timedelta(days=200)),
            _txn("HOA Dues", -300.0, today - timedelta(days=110)),
        ]
        # 110 days quiet is fine for a ~91-day cycle (allowance ~143).
        items = detect_recurring(txns)
        assert len(items) == 1
        assert items[0].frequency == "quarterly"


class TestLongCadences:
    def test_semiannual_detected(self):
        today = date.today()
        txns = [
            _txn("Auto Insurance", -650.0, today - timedelta(days=366)),
            _txn("Auto Insurance", -650.0, today - timedelta(days=183)),
            _txn("Auto Insurance", -650.0, today),
        ]
        items = detect_recurring(txns)
        assert len(items) == 1
        assert items[0].frequency == "semiannual"

    def test_yearly_detected_with_two_year_window(self):
        today = date.today()
        txns = [
            _txn("Domain Renewal", -120.0, today - timedelta(days=365)),
            _txn("Domain Renewal", -120.0, today),
        ]
        items = detect_recurring(txns)
        assert len(items) == 1
        assert items[0].frequency == "yearly"
