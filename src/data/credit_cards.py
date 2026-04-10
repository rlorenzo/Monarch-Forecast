"""Credit card statement balance estimation from transaction history.

Estimates upcoming CC payments by:
1. Using user-provided due date and statement close day (if set)
2. Inferring from payment history (last payment day-of-month)
3. Summing charges in the billing cycle (statement close to statement close)
4. Falling back to recurring payment amount or current balance
"""

from __future__ import annotations

import calendar
from datetime import date, timedelta
from typing import Any

from src.forecast.models import ForecastTransaction, RecurringItem

# Default grace period assumption when inferring statement close from due date
DEFAULT_GRACE_PERIOD = 25


def estimate_cc_payments(
    cc_accounts: list[dict[str, Any]],
    recurring_items: list[RecurringItem],
    forecast_days: int = 45,
    transactions: list[dict] | None = None,
    today: date | None = None,
    cc_settings: dict[str, dict[str, int]] | None = None,
    amount_overrides: dict[str, float] | None = None,
) -> list[ForecastTransaction]:
    """Estimate upcoming credit card payments.

    Args:
        cc_accounts: CC accounts with id, name, balance.
        recurring_items: Detected recurring items (fallback).
        forecast_days: How far out to forecast.
        transactions: Raw transaction history for charge summation.
        today: Override for current date (for testing).
        cc_settings: Per-CC billing settings from preferences.
            Format: {cc_id: {"due_day": int, "close_day": int}}
        amount_overrides: Per-CC amount overrides from user.
            Format: {cc_id: float}
    """
    if today is None:
        today = date.today()
    end = today + timedelta(days=forecast_days)
    txns = transactions or []
    settings = cc_settings or {}
    overrides = amount_overrides or {}
    payments: list[ForecastTransaction] = []

    for cc in cc_accounts:
        balance = cc.get("balance", 0.0)
        if balance >= 0:
            continue

        cc_id = cc.get("id", "")
        cc_name = cc.get("name", "Credit Card")

        # Try estimation from transaction history + settings
        cc_setting = settings.get(cc_id)
        result = _estimate_from_cycle(cc_id, cc_name, txns, today, end, cc_setting)
        if result:
            due_date, amount, label = result
        elif cc_setting:
            # User provided settings but no charges in cycle — nothing to pay
            continue
        else:
            # No settings and no cycle data — try fallbacks
            recurring = _find_recurring_cc(cc_name, recurring_items, today, end)
            if recurring:
                due_date, recurring_amount = recurring
                amount = abs(recurring_amount)
                label = "avg"
            else:
                # Last resort: current balance
                due_date = today + timedelta(days=DEFAULT_GRACE_PERIOD)
                if due_date > end:
                    continue
                amount = abs(balance)
                label = "est."

        # Apply user amount override if set
        if cc_id in overrides:
            amount = abs(overrides[cc_id])
            label = "manual"

        payments.append(
            ForecastTransaction(
                date=due_date,
                name=f"{cc_name} Payment ({label})",
                amount=-amount,
                category="Credit Card Payment",
                is_recurring=False,
            )
        )

    return payments


def _estimate_from_cycle(
    cc_id: str,
    cc_name: str,
    transactions: list[dict],
    today: date,
    end: date,
    user_settings: dict[str, int] | None,
) -> tuple[date, float, str] | None:
    """Estimate payment from billing cycle charges.

    Returns (due_date, amount, label) or None.
    """
    # Determine due_day and close_day
    if user_settings:
        due_day = user_settings.get("due_day", 0)
        close_day = user_settings.get("close_day", 0)
        if not due_day or not close_day:
            return None
    else:
        # Infer from payment history
        due_day = infer_due_day(cc_name, transactions)
        if not due_day:
            return None
        # Default: statement closes ~25 days before due date
        close_day = _day_minus(due_day, DEFAULT_GRACE_PERIOD)

    # Find the most recent statement close on or before today
    last_close = _most_recent_day_of_month(close_day, today)
    prev_close = _prev_month_day(last_close, close_day)

    # The statement that closed on last_close covers (prev_close, last_close]
    # That statement's due date is the next due_day after last_close
    next_due = _next_month_day(last_close, due_day)

    if next_due <= today:
        # We're past the due date for the last closed statement
        # Look at the NEXT cycle: (last_close, next_close]
        next_close = _next_month_day(last_close, close_day)
        cycle_start = last_close
        cycle_end = min(next_close, today)
        next_due = _next_month_day(next_close, due_day)
        label = "partial" if next_close > today else "stmt"
    else:
        # Due date is still upcoming — try the last closed cycle first
        cycle_start = prev_close
        cycle_end = last_close
        label = "stmt"

    if next_due > end:
        return None

    amount = _sum_cc_charges(cc_id, transactions, cycle_start, cycle_end)

    # If the closed cycle has no charges, check the open (next) cycle
    if amount == 0 and label == "stmt":
        next_close = _next_month_day(last_close, close_day)
        open_amount = _sum_cc_charges(cc_id, transactions, last_close, min(next_close, today))
        if open_amount > 0:
            next_due_open = _next_month_day(next_close, due_day)
            if next_due_open <= end:
                return next_due_open, open_amount, "partial"

    if amount == 0:
        return None

    return next_due, amount, label


def infer_due_day(cc_name: str, transactions: list[dict]) -> int:
    """Infer due day-of-month from payment history."""
    cc_name_lower = cc_name.lower()
    payment_days: list[int] = []

    for txn in transactions:
        amount = txn.get("amount", 0.0)
        if amount >= 0:
            continue  # Not a payment (outflow)

        merchant = (txn.get("merchant") or {}).get("name", "").lower()
        category = (txn.get("category") or {}).get("name", "").lower()
        combined = f"{merchant} {category}"

        # Check if this looks like a CC payment from checking
        if not _is_cc_payment_txn(combined, cc_name_lower):
            continue

        try:
            txn_date = date.fromisoformat(txn["date"][:10])
            payment_days.append(txn_date.day)
        except (ValueError, TypeError, KeyError):
            continue

    if not payment_days:
        return 0

    # Use the most common day, or the most recent
    from collections import Counter

    most_common = Counter(payment_days).most_common(1)[0][0]
    return most_common


def _sum_cc_charges(cc_id: str, transactions: list[dict], start: date, end: date) -> float:
    """Sum charges on a CC account between start (exclusive) and end (inclusive)."""
    total = 0.0
    for txn in transactions:
        account_id = (txn.get("account") or {}).get("id", "")
        if account_id != cc_id:
            continue
        amount = txn.get("amount", 0.0)
        if amount >= 0:
            continue  # Skip payments/credits, only charges

        try:
            txn_date = date.fromisoformat(txn["date"][:10])
        except (ValueError, TypeError, KeyError):
            continue

        if start < txn_date <= end:
            total += abs(amount)

    return total


def _is_cc_payment_txn(text: str, cc_name_lower: str) -> bool:
    """Check if transaction text looks like a payment to a specific CC."""
    payment_words = ["payment", "autopay", "credit card"]
    has_payment_word = any(w in text for w in payment_words)
    keywords = [w for w in cc_name_lower.split() if len(w) > 2]
    if not keywords:
        return has_payment_word
    keyword_match = sum(1 for kw in keywords if kw in text) >= len(keywords) / 2
    return keyword_match or (has_payment_word and any(kw in text for kw in keywords))


def _day_minus(day: int, n: int) -> int:
    """Subtract n days from a day-of-month, wrapping around."""
    result = day - n
    while result <= 0:
        result += 30
    return min(result, 28)  # Cap at 28 for safety


def _clamp_day(day: int, year: int, month: int) -> int:
    """Clamp a day to the valid range for a given month."""
    max_day = calendar.monthrange(year, month)[1]
    return min(day, max_day)


def _most_recent_day_of_month(day: int, ref: date) -> date:
    """Find the most recent occurrence of `day` on or before `ref`."""
    clamped = _clamp_day(day, ref.year, ref.month)
    candidate = ref.replace(day=clamped)
    if candidate <= ref:
        return candidate
    # Go to previous month
    return _prev_month_day(candidate, day)


def _prev_month_day(ref: date, day: int) -> date:
    """Get `day` of the month before `ref`."""
    if ref.month == 1:
        y, m = ref.year - 1, 12
    else:
        y, m = ref.year, ref.month - 1
    return date(y, m, _clamp_day(day, y, m))


def _next_month_day(ref: date, day: int) -> date:
    """Get the next occurrence of `day` after `ref`."""
    clamped = _clamp_day(day, ref.year, ref.month)
    candidate = ref.replace(day=clamped)
    if candidate > ref:
        return candidate
    # Next month
    if ref.month == 12:
        y, m = ref.year + 1, 1
    else:
        y, m = ref.year, ref.month + 1
    return date(y, m, _clamp_day(day, y, m))


def _find_recurring_cc(
    cc_name: str,
    recurring_items: list[RecurringItem],
    start: date,
    end: date,
) -> tuple[date, float] | None:
    """Find recurring CC payment amount and date as fallback."""
    cc_lower = cc_name.lower()
    for item in recurring_items:
        item_lower = f"{item.name} {item.category}".lower()
        keywords = [w for w in cc_lower.split() if len(w) > 2]
        if keywords and sum(1 for kw in keywords if kw in item_lower) >= len(keywords) / 2:
            from src.utils.date_helpers import next_occurrence

            occ = next_occurrence(item.base_date, item.frequency, start)
            if occ is not None and occ <= end:
                return occ, item.amount
    return None
