"""Synthetic data served by `DemoClient` when the user picks "Try Demo Mode".

Designed so the 45-day forecast shows a realistic dip-and-recover arc:
rent and a credit-card payment hit before the next paycheck, pushing
the balance into overdraft territory around days 7-13 and triggering the
low-balance alerts. Dates are generated relative to `date.today()` so the
demo is always fresh.
"""

from datetime import date, timedelta
from typing import Any

CHECKING_ID = "demo-checking"
CHECKING_NAME = "Everyday Checking"
CHECKING_STARTING_BALANCE = 1_950.00

CC_ID = "demo-cc"
CC_NAME = "Credit Card"
CC_BALANCE = -847.00

_PAYCHECK = 3_200.00
_RENT = -1_850.00

# Monthly expenses keyed on day-of-month for the recurring detector to pick up
# as "monthly" over 3 months of history.
_MONTHLY_ITEMS: list[tuple[int, float, str, str]] = [
    (1, _RENT, "Rent", "Housing"),
    (5, -22.00, "News Subscription", "Subscriptions"),
    (8, -12.00, "Streaming Music", "Subscriptions"),
    (12, -94.00, "Electric Bill", "Utilities"),
    (15, -89.00, "Internet", "Utilities"),
    (20, -18.00, "Streaming Video", "Subscriptions"),
]

# Weekly groceries — amounts must stay within ±20% of their median so the
# recurring detector accepts them as consistent.
_GROCERY_AMOUNTS = [-142.30, -156.75, -138.90, -149.50, -152.15, -145.80]

# Credit-card charges in the current cycle. Summed total = $847.00, matching
# the card's outstanding balance so the payment estimate lines up.
_CC_CHARGES: list[tuple[int, float, str, str]] = [
    (2, -67.40, "Gas Station", "Transportation"),
    (5, -42.10, "Coffee Shop", "Food"),
    (9, -156.30, "Hardware Store", "Shopping"),
    (14, -89.00, "Restaurant", "Food"),
    (19, -215.75, "Online Shopping", "Shopping"),
    (24, -276.45, "Furniture Store", "Shopping"),
]


def build_checking_accounts() -> list[dict[str, Any]]:
    return [
        {
            "id": CHECKING_ID,
            "name": CHECKING_NAME,
            "balance": CHECKING_STARTING_BALANCE,
            "institution": "Demo Bank",
            "type": "Depository",
            "subtype": "checking",
        }
    ]


def build_credit_card_accounts() -> list[dict[str, Any]]:
    return [
        {
            "id": CC_ID,
            "name": CC_NAME,
            "balance": CC_BALANCE,
            "institution": "Demo Bank",
        }
    ]


def build_transactions() -> list[dict[str, Any]]:
    """90 days of synthetic history, shaped for the recurring detector."""
    today = date.today()
    txns: list[dict[str, Any]] = []

    # Paychecks — biweekly. Offset so the most recent landed 4 days ago and
    # the next one arrives ~10 days out. This opens a gap around the next
    # rent payment, giving the chart a visible dip-and-recovery arc.
    for days_ago in range(4, 91, 14):
        txns.append(
            _make(today - timedelta(days=days_ago), _PAYCHECK, "Paycheck", "Income", CHECKING_ID)
        )

    # Monthly expenses across up to 4 months back (some will fall outside 90d).
    for day_of_month, amount, name, category in _MONTHLY_ITEMS:
        for offset in range(4):
            y, m = today.year, today.month - offset
            while m <= 0:
                m += 12
                y -= 1
            try:
                d = date(y, m, day_of_month)
            except ValueError:
                continue
            if d > today or (today - d).days > 90:
                continue
            txns.append(_make(d, amount, name, category, CHECKING_ID))

    # Weekly groceries — cycle through the amount list.
    for i, days_ago in enumerate(range(3, 91, 7)):
        txns.append(
            _make(
                today - timedelta(days=days_ago),
                _GROCERY_AMOUNTS[i % len(_GROCERY_AMOUNTS)],
                "Grocery Store",
                "Food",
                CHECKING_ID,
            )
        )

    # Credit-card charges in the current cycle.
    for days_ago, amount, merchant, category in _CC_CHARGES:
        txns.append(_make(today - timedelta(days=days_ago), amount, merchant, category, CC_ID))

    return txns


def _make(d: date, amount: float, merchant: str, category: str, acct_id: str) -> dict[str, Any]:
    acct_name = CHECKING_NAME if acct_id == CHECKING_ID else CC_NAME
    return {
        "id": f"demo-{merchant.replace(' ', '-').lower()}-{d.isoformat()}",
        "date": d.isoformat(),
        "amount": amount,
        "merchant": {"name": merchant},
        "category": {"name": category},
        "account": {"id": acct_id, "displayName": acct_name},
    }
