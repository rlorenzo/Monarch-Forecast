"""Detect recurring transactions from transaction history."""

from collections import defaultdict
from datetime import date, timedelta
from statistics import median

from src.forecast.models import RecurringItem


def detect_recurring(
    transactions: list[dict],
    min_occurrences: int = 2,
    lookback_days: int = 90,
) -> list[RecurringItem]:
    """Analyze transaction history to detect recurring patterns.

    Groups transactions by merchant, then checks if amounts and intervals
    are consistent enough to suggest a recurring pattern.

    Args:
        transactions: Raw transaction dicts with date, amount, merchant, category, account.
        min_occurrences: Minimum number of times a transaction must appear.
        lookback_days: How many days of history to consider.

    Returns:
        List of detected RecurringItems.
    """
    cutoff = date.today() - timedelta(days=lookback_days)

    # Group by merchant name
    by_merchant: dict[str, list[dict]] = defaultdict(list)
    for txn in transactions:
        merchant = (txn.get("merchant") or {}).get("name", "")
        if not merchant:
            continue
        txn_date_str = txn.get("date", "")
        try:
            txn_date = date.fromisoformat(txn_date_str[:10])
        except (ValueError, TypeError):
            continue
        if txn_date < cutoff:
            continue
        by_merchant[merchant].append(txn)

    items: list[RecurringItem] = []
    for merchant, txns in by_merchant.items():
        if len(txns) < min_occurrences:
            continue

        # Sort by date
        txns.sort(key=lambda t: t["date"])

        # Check amount consistency — amounts should be similar
        amounts = [t["amount"] for t in txns]
        median_amount = median(amounts)
        if median_amount == 0:
            continue

        # Allow 20% variance from median
        consistent_amounts = all(
            abs(a - median_amount) / abs(median_amount) < 0.2 for a in amounts if median_amount != 0
        )
        if not consistent_amounts:
            continue

        # Detect frequency from intervals between transactions
        dates = []
        for t in txns:
            try:
                dates.append(date.fromisoformat(t["date"][:10]))
            except (ValueError, TypeError):
                continue

        if len(dates) < min_occurrences:
            continue

        frequency = _detect_frequency(dates)
        if not frequency:
            continue

        # Use the most recent transaction as the base date
        base_date = dates[-1]
        category = (txns[-1].get("category") or {}).get("name", "")
        account_data = txns[-1].get("account") or {}
        account_id = account_data.get("id", "")
        account_name = account_data.get("displayName", "")

        items.append(
            RecurringItem(
                name=merchant,
                amount=median_amount,
                frequency=frequency,
                base_date=base_date,
                category=category,
                account_id=account_id,
                account_name=account_name,
            )
        )

    return items


def _detect_frequency(dates: list[date]) -> str | None:
    """Infer frequency from a list of sorted dates."""
    if len(dates) < 2:
        return None

    intervals = [(dates[i + 1] - dates[i]).days for i in range(len(dates) - 1)]
    avg_interval = sum(intervals) / len(intervals)

    # Weekly: ~7 days
    if 5 <= avg_interval <= 9:
        return "weekly"
    # Biweekly: ~14 days
    if 12 <= avg_interval <= 16:
        return "biweekly"
    # Semimonthly: ~15 days
    if 14 <= avg_interval <= 17:
        # Distinguish from biweekly by checking if dates cluster around
        # two specific days of the month
        days_of_month = [d.day for d in dates]
        unique_days = set(days_of_month)
        if len(unique_days) <= 3 and max(days_of_month) - min(days_of_month) > 5:
            return "semimonthly"
        return "biweekly"
    # Monthly: ~30 days
    if 25 <= avg_interval <= 35:
        return "monthly"
    # Yearly: ~365 days
    if 350 <= avg_interval <= 380:
        return "yearly"

    return None
