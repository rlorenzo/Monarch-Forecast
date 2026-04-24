"""Smoke tests for view modules — verify they don't crash on construction."""

import flet as ft

from tests.factories import make_forecast


class TestChartSmoke:
    def test_builds_chart(self):
        from src.views.chart import build_forecast_chart

        forecast = make_forecast()
        chart = build_forecast_chart(forecast)
        assert chart is not None

    def test_chart_with_threshold(self):
        from src.views.chart import build_forecast_chart

        forecast = make_forecast(balance=1000.0, threshold=2000.0)
        chart = build_forecast_chart(forecast)
        assert chart is not None


class TestAlertsSmoke:
    def test_build_alerts_banner_empty(self):
        from src.views.alerts import build_alerts_banner

        result = build_alerts_banner([])
        # When there are no alerts we return a bare empty Container — a
        # Semantics node with an empty Column would collapse to zero size
        # and Flet rejects that.
        assert isinstance(result, ft.Container)

    def test_build_alerts_banner_with_alerts(self):
        from src.views.alerts import Alert, build_alerts_banner

        alerts = [
            Alert(severity="critical", title="Overdraft", message="Balance negative"),
            Alert(severity="warning", title="Low", message="Below threshold"),
            Alert(severity="info", title="Large outflow", message="$3000 going out"),
        ]
        result = build_alerts_banner(alerts)
        assert isinstance(result, ft.Semantics)
        assert result.live_region is True
        assert result.label  # non-empty screen reader summary
        inner = result.content
        assert isinstance(inner, ft.Column)
        assert len(inner.controls) == 3


class TestTransactionsTableSmoke:
    def test_builds_table(self):
        from src.views.transactions_table import build_transactions_table

        forecast = make_forecast()
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
