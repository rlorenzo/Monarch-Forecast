"""Detect recurring transactions from transaction history."""

import re
from collections import defaultdict
from datetime import date, timedelta
from statistics import median

from src.data.models import RecurringItem

# How much history the detector (and the dashboard fetch that feeds it)
# looks at. 750 days fits two occurrences of a yearly renewal with margin
# (a shorter window structurally can't prove annual or semiannual
# cadences). Affordable because transaction history is cached
# incrementally (see cached_client): the long window downloads once, then
# each load fetches only the recent delta. The staleness guard below
# keeps old history from resurrecting dead streams.
DEFAULT_LOOKBACK_DAYS = 750

# An amount counts as consistent when it's within this fraction of the
# group's median. Membership is per-transaction (see below) rather than
# all-or-nothing, so one refund or one-off purchase at a recurring
# merchant no longer disqualifies the whole stream.
_AMOUNT_TOLERANCE = 0.25

# At least this fraction of a group's transactions must be amount-consistent
# for the group to count as recurring at all.
_MIN_CONSISTENT_FRACTION = 0.5

# Penalty fees are event-driven consequences, not schedulable bills. A pair
# of $22 NSF fees a month apart pattern-matches as "monthly recurring", but
# projecting a penalty forward bakes the exact failure this app exists to
# prevent into the forecast. Phrases are substring-matched; "nsf" is matched
# as a whole word only ("transfer" contains the letters n-s-f).
_PENALTY_PHRASES = (
    "non-sufficient",
    "nonsufficient",
    "non sufficient",
    "insufficient funds",
    "overdraft",
    "late fee",
    "late payment fee",
    "returned item",
    "penalty",
)


def _is_penalty_fee(name: str, category: str) -> bool:
    text = f"{name} {category}".lower()
    if any(phrase in text for phrase in _PENALTY_PHRASES):
        return True
    return "nsf" in re.findall(r"[a-z]+", text)


# Bare generic bank descriptors name an event type, not a counterparty.
# Grouping them lumps unrelated one-offs together ("Deposit" of $63.05 and
# another of $58 two weeks later is not a biweekly income stream). Matched
# exactly against the normalized name, so "Home Depot" or a payroll
# descriptor containing "deposit" is unaffected.
_GENERIC_DESCRIPTORS = frozenset(
    {
        "deposit",
        "mobile deposit",
        "atm deposit",
        "withdrawal",
        "atm withdrawal",
        "atm",
        "check",
        "checks",
        "cash",
        "debit",
        "credit",
        "pos",
        "payment",
        "transfer",
        "online transfer",
        "misc",
        "other",
    }
)


def _is_generic_descriptor(name: str) -> bool:
    normalized = " ".join(re.findall(r"[a-z0-9]+", name.lower()))
    return normalized in _GENERIC_DESCRIPTORS


# Nominal cycle length per cadence, for the staleness guard.
_CYCLE_DAYS = {
    "weekly": 7,
    "biweekly": 14,
    "semimonthly": 15,
    "monthly": 30,
    "bimonthly": 61,
    "quarterly": 91,
    "semiannual": 183,
    "yearly": 365,
}


def detect_recurring(
    transactions: list[dict],
    min_occurrences: int = 2,
    lookback_days: int = DEFAULT_LOOKBACK_DAYS,
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

    # Group by (merchant name, account id). A merchant string like "Ameriprise"
    # can cover independent recurring streams on different accounts (e.g. two
    # household members' insurance debits) — merging them produces a polluted
    # bag whose median amount and average interval describe neither stream.
    by_group: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for txn in transactions:
        # Fall back to the raw bank descriptor when Monarch has no merchant
        # (rent by check, ACH debits). Descriptors are noisier but grouping
        # on them gives those streams a chance instead of none.
        merchant = (txn.get("merchant") or {}).get("name", "") or str(txn.get("plaidName") or "")
        if not merchant:
            continue
        # Monarch can send an explicit JSON null amount; comparing None
        # against 0 downstream would abort detection (and dashboard load).
        if not isinstance(txn.get("amount"), (int, float)):
            continue
        if _is_penalty_fee(merchant, (txn.get("category") or {}).get("name", "")):
            continue
        if _is_generic_descriptor(merchant):
            continue
        account_id = (txn.get("account") or {}).get("id", "")
        txn_date_str = txn.get("date", "")
        try:
            txn_date = date.fromisoformat(txn_date_str[:10])
        except (ValueError, TypeError):
            continue
        if txn_date < cutoff:
            continue
        by_group[(merchant, account_id)].append(txn)

    items: list[RecurringItem] = []
    for (merchant, _account_id), txns in by_group.items():
        if len(txns) < min_occurrences:
            continue

        # Sort by date
        txns.sort(key=lambda t: t["date"])

        # A recurring stream has one sign; refunds or interest credits at
        # the same merchant would flip the median and wreck the variance
        # check, so analyze the majority-sign subset only.
        negatives = [t for t in txns if t["amount"] < 0]
        positives = [t for t in txns if t["amount"] > 0]
        candidates = negatives if len(negatives) >= len(positives) else positives
        if len(candidates) < min_occurrences:
            continue

        # Amount consistency — per-transaction membership against the
        # median, not all-or-nothing: one outlier (annual true-up, extra
        # purchase at a subscription merchant) drops out of the stream
        # instead of disqualifying it.
        amounts = [t["amount"] for t in candidates]
        group_median = median(amounts)
        if group_median == 0:
            continue
        consistent = [
            t
            for t in candidates
            if abs(t["amount"] - group_median) / abs(group_median) <= _AMOUNT_TOLERANCE
        ]
        if len(consistent) < min_occurrences:
            continue
        if len(consistent) / len(candidates) < _MIN_CONSISTENT_FRACTION:
            continue

        # Detect frequency from intervals between transactions
        dates = []
        for t in consistent:
            try:
                dates.append(date.fromisoformat(t["date"][:10]))
            except (ValueError, TypeError):
                continue

        # Same-day duplicates (split charges) are one occurrence, not two;
        # a 0-day interval would otherwise drag the typical interval out of
        # every band.
        unique_dates = sorted(set(dates))
        if len(unique_dates) < min_occurrences:
            continue

        frequency = _detect_frequency(unique_dates)
        if not frequency:
            continue

        # Two data points a fortnight apart are a coincidence, not a
        # schedule: short cadences get many chances to recur inside the
        # window, so demand a third occurrence before believing them.
        # Monthly and slower keep the 2-occurrence floor — the window
        # itself caps how many occurrences can exist.
        if frequency in ("weekly", "biweekly", "semimonthly") and len(unique_dates) < 3:
            continue

        # Staleness: a stream that has gone quiet is history, not a
        # schedule. With a two-year window, a subscription cancelled last
        # spring would otherwise keep projecting forward. Allow 1.5 cycles
        # plus a week of posting slack since the last occurrence.
        cycle = _CYCLE_DAYS[frequency]
        if (date.today() - unique_dates[-1]).days > cycle * 1.5 + 7:
            continue

        # Use the most recent transaction as the base date
        base_date = unique_dates[-1]
        median_amount = median(t["amount"] for t in consistent)
        category = (consistent[-1].get("category") or {}).get("name", "")
        account_data = consistent[-1].get("account") or {}
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
    """Infer frequency from a list of sorted, de-duplicated dates.

    Uses the median interval rather than the mean: one missed or failed
    charge turns a monthly pattern's mean from ~30 to ~45 days (outside
    every band), while the median stays on the true cadence.
    """
    if len(dates) < 2:
        return None

    intervals = sorted((dates[i + 1] - dates[i]).days for i in range(len(dates) - 1))
    typical = median(intervals)

    # A band only counts if the intervals actually cluster around the
    # median. Four sightings of a bank descriptor that got renamed midway
    # ("Subscription" vs "Subscription Withdrawal") sat [30, 91, 305] days
    # apart: the median lands squarely in the quarterly band while
    # describing no schedule at all. Require a majority of intervals
    # within ±35% of the median (small absolute floor for weekly jitter).
    tolerance = max(typical * 0.35, 4)
    near = [i for i in intervals if abs(i - typical) <= tolerance]
    if len(near) < (len(intervals) + 1) // 2:
        return None

    # Weekly: ~7 days
    if 5 <= typical <= 9:
        return "weekly"
    # Biweekly vs semimonthly: ~14-17 days. Semimonthly (1st/15th style)
    # clusters on a few specific days of the month; biweekly drifts across
    # the calendar. The cluster test needs at least four dates to mean
    # anything (three dates always have <= 3 unique days-of-month), so
    # sparser streams default to biweekly, the more common pattern.
    if 12 <= typical <= 17:
        days_of_month = [d.day for d in dates]
        unique_days = set(days_of_month)
        if (
            len(dates) >= 4
            and len(unique_days) <= 3
            and max(days_of_month) - min(days_of_month) > 5
        ):
            return "semimonthly"
        return "biweekly"
    # Monthly: ~30 days
    if 25 <= typical <= 35:
        return "monthly"
    # Bimonthly: ~61 days (water/trash utilities are often billed this way)
    if 55 <= typical <= 70:
        return "bimonthly"
    # Quarterly: ~91 days (insurance premiums, HOA dues)
    if 80 <= typical <= 100:
        return "quarterly"
    # Semiannual: ~183 days (auto insurance, vehicle registration)
    if 165 <= typical <= 200:
        return "semiannual"
    # Yearly: ~365 days
    if 350 <= typical <= 380:
        return "yearly"

    return None
