"""Tests for recurring transaction detection algorithm."""

from datetime import date, timedelta

from src.data.recurring_detector import _detect_frequency, detect_recurring


def _make_txn(
    merchant: str,
    amount: float,
    txn_date: date,
    category: str = "",
    account_id: str = "acct1",
) -> dict:
    return {
        "merchant": {"name": merchant, "id": "m1"},
        "amount": amount,
        "date": txn_date.isoformat(),
        "category": {"name": category},
        "account": {"id": account_id, "displayName": "Checking"},
    }


class TestDetectFrequency:
    def test_weekly(self):
        dates = [date(2026, 1, 5 + i * 7) for i in range(4)]
        assert _detect_frequency(dates) == "weekly"

    def test_biweekly(self):
        base = date(2026, 1, 2)
        dates = [base + timedelta(days=i * 14) for i in range(4)]
        assert _detect_frequency(dates) == "biweekly"

    def test_monthly(self):
        dates = [date(2026, 1, 15), date(2026, 2, 15), date(2026, 3, 15)]
        assert _detect_frequency(dates) == "monthly"

    def test_single_date_returns_none(self):
        assert _detect_frequency([date(2026, 1, 1)]) is None

    def test_irregular_returns_none(self):
        # Intervals: 2 days, 45 days — average 23.5 doesn't match any pattern
        dates = [date(2026, 1, 1), date(2026, 1, 3), date(2026, 2, 17)]
        assert _detect_frequency(dates) is None


class TestDetectRecurring:
    def test_detects_monthly(self):
        today = date.today()
        txns = [
            _make_txn("Netflix", -15.99, today - timedelta(days=60)),
            _make_txn("Netflix", -15.99, today - timedelta(days=30)),
            _make_txn("Netflix", -15.99, today - timedelta(days=1)),
        ]
        items = detect_recurring(txns)
        assert len(items) == 1
        assert items[0].name == "Netflix"
        assert items[0].frequency == "monthly"
        assert items[0].amount == -15.99

    def test_skips_inconsistent_amounts(self):
        today = date.today()
        txns = [
            _make_txn("Random Store", -10.00, today - timedelta(days=60)),
            _make_txn("Random Store", -50.00, today - timedelta(days=30)),
            _make_txn("Random Store", -200.00, today - timedelta(days=1)),
        ]
        items = detect_recurring(txns)
        assert len(items) == 0

    def test_skips_single_occurrence(self):
        txns = [_make_txn("One Time", -100.00, date.today() - timedelta(days=5))]
        items = detect_recurring(txns)
        assert len(items) == 0

    def test_detects_biweekly(self):
        today = date.today()
        txns = [
            _make_txn("Paycheck", 2000.0, today - timedelta(days=42)),
            _make_txn("Paycheck", 2000.0, today - timedelta(days=28)),
            _make_txn("Paycheck", 2000.0, today - timedelta(days=14)),
            _make_txn("Paycheck", 2000.0, today - timedelta(days=0)),
        ]
        items = detect_recurring(txns)
        assert len(items) == 1
        assert items[0].frequency == "biweekly"
        assert items[0].amount == 2000.0

    def test_same_merchant_on_different_accounts_stays_split(self):
        # Two genuinely-monthly Ameriprise streams on different accounts —
        # one on the 16th for $1100, one on the 25th for $1000. Grouping by
        # merchant alone would interleave them into a bag whose median is
        # $1050 and whose avg interval lands in the biweekly bucket.
        today = date.today()
        txns = [
            _make_txn("Ameriprise", -1000.0, today - timedelta(days=89), account_id="karen"),
            _make_txn("Ameriprise", -1100.0, today - timedelta(days=66), account_id="rex"),
            _make_txn("Ameriprise", -1000.0, today - timedelta(days=58), account_id="karen"),
            _make_txn("Ameriprise", -1100.0, today - timedelta(days=39), account_id="rex"),
            _make_txn("Ameriprise", -1000.0, today - timedelta(days=30), account_id="karen"),
            _make_txn("Ameriprise", -1100.0, today - timedelta(days=8), account_id="rex"),
        ]
        items = detect_recurring(txns)
        assert len(items) == 2
        by_account = {item.account_id: item for item in items}
        assert by_account["karen"].frequency == "monthly"
        assert by_account["karen"].amount == -1000.0
        assert by_account["rex"].frequency == "monthly"
        assert by_account["rex"].amount == -1100.0

    def test_includes_account_info(self):
        today = date.today()
        txns = [
            {
                "merchant": {"name": "Rent", "id": "m1"},
                "amount": -1500.0,
                "date": (today - timedelta(days=60)).isoformat(),
                "category": {"name": "Housing"},
                "account": {"id": "acct-123", "displayName": "Main Checking"},
            },
            {
                "merchant": {"name": "Rent", "id": "m1"},
                "amount": -1500.0,
                "date": (today - timedelta(days=30)).isoformat(),
                "category": {"name": "Housing"},
                "account": {"id": "acct-123", "displayName": "Main Checking"},
            },
            {
                "merchant": {"name": "Rent", "id": "m1"},
                "amount": -1500.0,
                "date": today.isoformat(),
                "category": {"name": "Housing"},
                "account": {"id": "acct-123", "displayName": "Main Checking"},
            },
        ]
        items = detect_recurring(txns)
        assert len(items) == 1
        assert items[0].account_id == "acct-123"
        assert items[0].account_name == "Main Checking"
        assert items[0].category == "Housing"
