"""Test data factories shared across test modules."""

from datetime import date

from src.data.models import ForecastTransaction
from src.forecast.models import ForecastDay, ForecastResult


def make_forecast(
    balance: float = 5000.0,
    days_out: int = 7,
    threshold: float = 500.0,
) -> ForecastResult:
    """Build a ForecastResult with a single rent charge on day 3.

    Used by view smoke tests and UI-integrity tests that need a populated
    forecast without caring about exact numbers. The alerts and accessibility
    suites construct richer forecasts inline because they assert on specific
    transaction shapes.
    """
    days = []
    b = balance
    for i in range(days_out):
        d = date(2026, 1, 1 + i)
        txns = []
        if i == 2:
            txns = [ForecastTransaction(date=d, name="Rent", amount=-1500.0, category="Housing")]
        day = ForecastDay(date=d, starting_balance=b, transactions=txns)
        b = day.ending_balance
        days.append(day)
    return ForecastResult(days=days, starting_balance=balance, safety_threshold=threshold)
