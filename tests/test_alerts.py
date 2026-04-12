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

    def test_merged_overdraft_and_threshold_breach(self):
        """When balance skips the band and drops straight from above-threshold
        to negative, the two alerts should be merged into one critical alert."""
        forecast = _make_forecast(
            1000.0,
            expenses=[(date(2026, 1, 5), -1600.0)],
            threshold=500.0,
        )
        alerts = generate_alerts(forecast, safety_threshold=500.0)
        critical = [a for a in alerts if a.severity == "critical"]
        warnings = [a for a in alerts if a.severity == "warning"]
        assert len(critical) == 1
        assert len(warnings) == 0
        assert "Overdraft & Below Safety Threshold" in critical[0].title

    def test_separate_warning_and_critical_when_band_exists(self):
        """Multi-day slide: first dips into the warning band, later goes negative.
        Both a warning and a critical alert should fire."""
        forecast = _make_forecast(
            1000.0,
            expenses=[
                (date(2026, 1, 5), -600.0),  # 400 — warning band
                (date(2026, 1, 6), -500.0),  # -100 — overdraft
            ],
            threshold=500.0,
        )
        alerts = generate_alerts(forecast, safety_threshold=500.0)
        assert any(a.severity == "critical" for a in alerts)
        assert any(a.severity == "warning" for a in alerts)

    def test_large_outflows_collapsed_into_single_alert(self):
        """Multiple large outflow days should produce one bulleted info alert,
        not one per day."""
        forecast = _make_forecast(
            20000.0,
            expenses=[
                (date(2026, 1, 5), -2500.0),
                (date(2026, 1, 10), -3000.0),
                (date(2026, 1, 15), -2100.0),
            ],
            threshold=500.0,
        )
        alerts = generate_alerts(forecast, safety_threshold=500.0)
        info = [a for a in alerts if a.severity == "info"]
        assert len(info) == 1
        assert info[0].title == "Large Outflows"
        assert info[0].message.count("\u2022") == 3

    def test_single_large_outflow_uses_singular_title(self):
        forecast = _make_forecast(
            20000.0,
            expenses=[(date(2026, 1, 5), -2500.0)],
            threshold=500.0,
        )
        alerts = generate_alerts(forecast, safety_threshold=500.0)
        info = [a for a in alerts if a.severity == "info"]
        assert len(info) == 1
        assert info[0].title == "Large Outflow"
