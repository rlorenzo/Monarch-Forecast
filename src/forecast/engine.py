"""Core forecast engine: projects checking account balance day-by-day."""

from datetime import date, timedelta

from src.forecast.models import (
    ForecastDay,
    ForecastResult,
    ForecastTransaction,
    RecurringItem,
)
from src.utils.date_helpers import occurrences_in_range


def build_forecast(
    starting_balance: float,
    recurring_items: list[RecurringItem],
    one_off_transactions: list[ForecastTransaction] | None = None,
    start_date: date | None = None,
    days_out: int = 45,
    safety_threshold: float = 0.0,
) -> ForecastResult:
    """Build a day-by-day balance forecast.

    Args:
        starting_balance: Current checking account balance.
        recurring_items: All recurring income and expenses.
        one_off_transactions: Manual/one-off expected transactions.
        start_date: Forecast start date (defaults to today).
        days_out: How many days to project forward.
        safety_threshold: Balance level to flag as a shortfall.

    Returns:
        A ForecastResult with day-by-day projections.
    """
    if start_date is None:
        start_date = date.today()
    end_date = start_date + timedelta(days=days_out - 1)

    # Build a map of date -> list of transactions
    txn_by_date: dict[date, list[ForecastTransaction]] = {}

    for item in recurring_items:
        for occ_date in occurrences_in_range(item.base_date, item.frequency, start_date, end_date):
            txn = ForecastTransaction(
                date=occ_date,
                name=item.name,
                amount=item.amount,
                category=item.category,
                is_recurring=True,
            )
            txn_by_date.setdefault(occ_date, []).append(txn)

    if one_off_transactions:
        for txn in one_off_transactions:
            if start_date <= txn.date <= end_date:
                txn_by_date.setdefault(txn.date, []).append(txn)

    # Walk day-by-day
    forecast_days: list[ForecastDay] = []
    balance = starting_balance

    current = start_date
    while current <= end_date:
        day_txns = txn_by_date.get(current, [])
        day = ForecastDay(
            date=current,
            starting_balance=balance,
            transactions=day_txns,
        )
        balance = day.ending_balance
        forecast_days.append(day)
        current += timedelta(days=1)

    return ForecastResult(
        days=forecast_days,
        starting_balance=starting_balance,
        safety_threshold=safety_threshold,
    )
