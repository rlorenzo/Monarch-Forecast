"""Utilities for categorizing and summarizing recurring transactions."""

from src.data.models import RecurringItem, TransactionType


def group_by_type(
    items: list[RecurringItem],
) -> dict[str, list[RecurringItem]]:
    """Group recurring items into income, fixed expenses, and credit card payments."""
    groups: dict[str, list[RecurringItem]] = {
        "income": [],
        "credit_card": [],
        "expenses": [],
    }
    for item in items:
        if item.transaction_type == TransactionType.INCOME:
            groups["income"].append(item)
        elif item.is_credit_card_payment:
            groups["credit_card"].append(item)
        else:
            groups["expenses"].append(item)
    return groups


def monthly_total(items: list[RecurringItem]) -> float:
    """Estimate the total monthly impact of a list of recurring items."""
    total = 0.0
    for item in items:
        freq = item.frequency
        if freq == "weekly":
            total += item.amount * 4.33
        elif freq == "biweekly":
            total += item.amount * 2.17
        elif freq in ("monthly", "semimonthly"):
            multiplier = 1 if freq == "monthly" else 2
            total += item.amount * multiplier
        elif freq == "yearly":
            total += item.amount / 12
        else:
            total += item.amount
    return total
