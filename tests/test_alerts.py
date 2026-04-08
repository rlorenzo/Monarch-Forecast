"""Tests for forecast alerts."""

from datetime import date

from src.forecast.models import ForecastDay, ForecastResult, ForecastTransaction
from src.views.alerts import generate_alerts


def _make_forecast(
    balance: float,
    expenses: list[tuple[date, float]] | None = None,
    threshold: float = 500.0,
) -> ForecastResult:
    days = []
    b = balance
    if expenses:
        for d, amount in expenses:
            txns = [ForecastTransaction(date=d, name="Expense", amount=amount)]
            day = ForecastDay(date=d, starting_balance=b, transactions=txns)
            b = day.ending_balance
            days.append(day)
    return ForecastResult(days=days, starting_balance=balance, safety_threshold=threshold)


class TestGenerateAlerts:
    def test_no_alerts_healthy_forecast(self):
        forecast = _make_forecast(10000.0)
        alerts = generate_alerts(forecast, safety_threshold=500.0)
        assert len(alerts) == 0

    def test_shortfall_alert(self):
        forecast = _make_forecast(
            1000.0,
            expenses=[(date(2026, 1, 5), -1600.0)],
            threshold=500.0,
        )
        alerts = generate_alerts(forecast, safety_threshold=500.0)
        assert any(a.severity == "critical" for a in alerts)

    def test_low_balance_warning(self):
        forecast = _make_forecast(
            1000.0,
            expenses=[(date(2026, 1, 5), -600.0)],
            threshold=500.0,
        )
        alerts = generate_alerts(forecast, safety_threshold=500.0)
        assert len(alerts) > 0
