"""Smoke tests for view modules — verify they don't crash on construction."""

from datetime import date
from pathlib import Path

import flet as ft

from src.data.history import ForecastHistory
from src.forecast.models import (
    ForecastDay,
    ForecastResult,
    ForecastTransaction,
)


def _make_forecast(
    balance: float = 5000.0,
    days_out: int = 7,
    threshold: float = 500.0,
) -> ForecastResult:
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


class TestAccuracyViewSmoke:
    def test_no_data(self, tmp_path: Path):
        from src.views.accuracy import build_accuracy_view

        history = ForecastHistory(db_path=tmp_path / "test.db")
        result = build_accuracy_view(history, "acct1")
        assert isinstance(result, ft.Column)
        history.close()

    def test_with_data(self, tmp_path: Path):
        from src.views.accuracy import build_accuracy_view

        history = ForecastHistory(db_path=tmp_path / "test.db")
        # Seed some data
        snapshot = "2026-01-01"
        for i in range(5):
            target = f"2026-04-0{i + 1}"
            history._conn.execute(
                "INSERT INTO forecast_snapshots VALUES (NULL,?,?,?,?)",
                (snapshot, "acct1", target, 5000.0 + i * 100),
            )
            history._conn.execute(
                "INSERT INTO actual_balances VALUES (NULL,?,?,?)",
                (target, "acct1", 4900.0 + i * 50),
            )
        history._conn.commit()

        result = build_accuracy_view(history, "acct1")
        assert isinstance(result, ft.Column)
        history.close()


class TestChartSmoke:
    def test_builds_chart(self):
        from src.views.chart import build_forecast_chart

        forecast = _make_forecast()
        chart = build_forecast_chart(forecast)
        assert chart is not None

    def test_chart_with_threshold(self):
        from src.views.chart import build_forecast_chart

        forecast = _make_forecast(balance=1000.0, threshold=2000.0)
        chart = build_forecast_chart(forecast)
        assert chart is not None


class TestAlertsSmoke:
    def test_build_alerts_banner_empty(self):
        from src.views.alerts import build_alerts_banner

        result = build_alerts_banner([])
        assert isinstance(result, ft.Column)

    def test_build_alerts_banner_with_alerts(self):
        from src.views.alerts import Alert, build_alerts_banner

        alerts = [
            Alert(severity="critical", title="Overdraft", message="Balance negative"),
            Alert(severity="warning", title="Low", message="Below threshold"),
            Alert(severity="info", title="Large outflow", message="$3000 going out"),
        ]
        result = build_alerts_banner(alerts)
        assert isinstance(result, ft.Column)
        assert len(result.controls) == 3


class TestTransactionsTableSmoke:
    def test_builds_table(self):
        from src.views.transactions_table import build_transactions_table

        forecast = _make_forecast()
        table = build_transactions_table(forecast)
        assert isinstance(table, ft.DataTable)
        assert len(table.columns) == 5


class TestUpdateBannerSmoke:
    def test_builds_banner(self):
        from src.views.update_banner import build_update_banner

        info = {
            "version": "0.2.0",
            "download_url": "https://example.com/dl",
            "html_url": "https://example.com",
        }
        banner = build_update_banner(info)
        assert isinstance(banner, ft.Container)
