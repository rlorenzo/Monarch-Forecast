"""Credit card statement estimation from recent spending."""

from datetime import date, timedelta
from typing import Any

from src.forecast.models import ForecastTransaction, RecurringItem


def estimate_cc_payments(
    cc_accounts: list[dict[str, Any]],
    recurring_items: list[RecurringItem],
    forecast_days: int = 45,
) -> list[ForecastTransaction]:
    """Estimate upcoming credit card payments as forecast transactions.

    Uses current CC balance as the estimated next statement amount.
    If a recurring payment already exists for the card, uses that date;
    otherwise assumes payment due ~25 days from now (typical billing cycle).

    Args:
        cc_accounts: Credit card accounts with id, name, balance.
        recurring_items: Existing recurring items (to find CC payment dates).
        forecast_days: How far out to look.

    Returns:
        List of ForecastTransactions representing estimated CC payments.
    """
    today = date.today()
    end = today + timedelta(days=forecast_days)
    payments: list[ForecastTransaction] = []

    for cc in cc_accounts:
        balance = cc.get("balance", 0.0)
        if balance >= 0:
            # No balance owed (or credit), skip
            continue

        # Amount owed is the absolute value of the negative balance
        payment_amount = abs(balance)
        cc_name = cc.get("name", "Credit Card")

        # Try to find a matching recurring payment
        payment_date = _find_recurring_cc_date(cc_name, recurring_items, today, end)

        if payment_date is None:
            # Default: assume payment due ~25 days from now
            payment_date = today + timedelta(days=25)
            if payment_date > end:
                continue

        payments.append(
            ForecastTransaction(
                date=payment_date,
                name=f"{cc_name} Payment (est.)",
                amount=-payment_amount,
                category="Credit Card Payment",
                is_recurring=False,
            )
        )

    return payments


def _find_recurring_cc_date(
    cc_name: str,
    recurring_items: list[RecurringItem],
    start: date,
    end: date,
) -> date | None:
    """Find the next payment date for a credit card from recurring items."""
    cc_lower = cc_name.lower()
    for item in recurring_items:
        item_lower = f"{item.name} {item.category}".lower()
        # Match by card name or credit card payment flag
        if _names_match(cc_lower, item_lower):
            from src.utils.date_helpers import next_occurrence
            occ = next_occurrence(item.base_date, item.frequency, start)
            if occ is not None and occ <= end:
                return occ
    return None


def _names_match(cc_name: str, item_name: str) -> bool:
    """Fuzzy match between credit card name and recurring item name."""
    # Check if key words from the CC name appear in the item
    keywords = [w for w in cc_name.split() if len(w) > 2]
    if not keywords:
        return False
    return sum(1 for kw in keywords if kw in item_name) >= len(keywords) / 2
