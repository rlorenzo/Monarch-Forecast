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

    Uses the recurring payment amount (from transaction history) as the best
    estimate of the statement balance. Falls back to the current balance only
    if no recurring payment history is found.

    Args:
        cc_accounts: Credit card accounts with id, name, balance.
        recurring_items: Existing recurring items (to find CC payment dates/amounts).
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
            continue

        cc_name = cc.get("name", "Credit Card")

        # Try to find a matching recurring payment — use its amount and date
        recurring_match = _find_recurring_cc_match(cc_name, recurring_items, today, end)

        if recurring_match:
            payment_date, recurring_amount = recurring_match
            # Use the recurring payment amount (historical average) as the
            # statement balance estimate — more accurate than current balance
            payment_amount = abs(recurring_amount)
            label = f"{cc_name} Payment (avg)"
        else:
            # Fallback: current balance, estimated date
            payment_amount = abs(balance)
            payment_date = today + timedelta(days=25)
            if payment_date > end:
                continue
            label = f"{cc_name} Payment (est.)"

        payments.append(
            ForecastTransaction(
                date=payment_date,
                name=label,
                amount=-payment_amount,
                category="Credit Card Payment",
                is_recurring=False,
            )
        )

    return payments


def _find_recurring_cc_match(
    cc_name: str,
    recurring_items: list[RecurringItem],
    start: date,
    end: date,
) -> tuple[date, float] | None:
    """Find the next payment date and amount for a credit card from recurring items."""
    cc_lower = cc_name.lower()
    for item in recurring_items:
        item_lower = f"{item.name} {item.category}".lower()
        if _names_match(cc_lower, item_lower):
            from src.utils.date_helpers import next_occurrence

            occ = next_occurrence(item.base_date, item.frequency, start)
            if occ is not None and occ <= end:
                return occ, item.amount
    return None


def _names_match(cc_name: str, item_name: str) -> bool:
    """Fuzzy match between credit card name and recurring item name."""
    # Check if key words from the CC name appear in the item
    keywords = [w for w in cc_name.split() if len(w) > 2]
    if not keywords:
        return False
    return sum(1 for kw in keywords if kw in item_name) >= len(keywords) / 2
