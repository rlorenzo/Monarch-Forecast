"""UI integrity tests — catch Flet API breakage, deprecated usage, and layout issues.

These tests instantiate real UI components with mocked dependencies to catch
runtime errors (wrong kwargs, removed attributes, renamed methods) without
needing a live Flet app window.
"""

import warnings
from pathlib import Path
from unittest.mock import patch

import flet as ft

from src.data.history import ForecastHistory
from src.forecast.models import ForecastDay, ForecastResult, ForecastTransaction


def _make_forecast(balance: float = 5000.0, days_out: int = 7) -> ForecastResult:
    from datetime import date

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
    return ForecastResult(days=days, starting_balance=balance, safety_threshold=500.0)


class TestNoDeprecationWarnings:
    """Ensure no Flet deprecation warnings fire during module import."""

    def test_all_modules_import_without_deprecation(self):
        import importlib

        modules = [
            "src.main",
            "src.auth.login_view",
            "src.views.accuracy",
            "src.views.adjustments",
            "src.views.alerts",
            "src.views.chart",
            "src.views.dashboard",
            "src.views.transactions_table",
            "src.views.update_banner",
        ]
        for mod in modules:
            with warnings.catch_warnings():
                warnings.filterwarnings("error", category=DeprecationWarning)
                m = importlib.import_module(mod)
                importlib.reload(m)

    @patch("src.auth.session_manager.keyring")
    def test_view_construction_no_deprecation(self, mock_keyring, tmp_path: Path, monkeypatch):
        """Instantiating views should not trigger Flet deprecation warnings."""
        from src.auth.login_view import LoginView
        from src.auth.session_manager import SessionManager
        from src.views.adjustments import AdjustmentsPanel
        from src.views.dashboard import DashboardView

        monkeypatch.setattr("src.auth.session_manager.SESSION_DIR", tmp_path)
        monkeypatch.setattr("src.auth.session_manager.SESSION_FILE", tmp_path / "s.pickle")
        monkeypatch.setattr("src.data.cache.CACHE_DB", tmp_path / "cache.db")
        monkeypatch.setattr("src.data.history.HISTORY_DB", tmp_path / "history.db")
        mock_keyring.get_password.return_value = None

        with warnings.catch_warnings():
            warnings.filterwarnings("error", category=DeprecationWarning)
            sm = SessionManager()
            LoginView(session_manager=sm, on_login_success=lambda: None)
            DashboardView(session_manager=sm, on_logout=lambda: None)
            AdjustmentsPanel(recurring_items=[], on_change=lambda: None)


class TestLoginViewInit:
    """LoginView instantiation catches API breakage (wrong kwargs, removed attrs)."""

    @patch("src.auth.session_manager.keyring")
    def test_creates_without_error(self, mock_keyring, tmp_path: Path, monkeypatch):
        from src.auth.login_view import LoginView
        from src.auth.session_manager import SessionManager

        monkeypatch.setattr("src.auth.session_manager.SESSION_DIR", tmp_path)
        monkeypatch.setattr("src.auth.session_manager.SESSION_FILE", tmp_path / "s.pickle")
        mock_keyring.get_password.return_value = None

        sm = SessionManager()
        view = LoginView(session_manager=sm, on_login_success=lambda: None)
        assert isinstance(view, ft.Column)
        assert len(view.controls) > 0


class TestDashboardViewInit:
    """DashboardView instantiation catches API breakage."""

    @patch("src.auth.session_manager.keyring")
    def test_creates_without_error(self, mock_keyring, tmp_path: Path, monkeypatch):
        from src.auth.session_manager import SessionManager
        from src.views.dashboard import DashboardView

        monkeypatch.setattr("src.auth.session_manager.SESSION_DIR", tmp_path)
        monkeypatch.setattr("src.auth.session_manager.SESSION_FILE", tmp_path / "s.pickle")
        monkeypatch.setattr("src.data.cache.CACHE_DB", tmp_path / "cache.db")
        monkeypatch.setattr("src.data.history.HISTORY_DB", tmp_path / "history.db")

        sm = SessionManager()
        dashboard = DashboardView(session_manager=sm, on_logout=lambda: None)
        assert isinstance(dashboard, ft.Column)
        assert len(dashboard.controls) > 0

    @patch("src.auth.session_manager.keyring")
    def test_has_tabs(self, mock_keyring, tmp_path: Path, monkeypatch):
        from src.auth.session_manager import SessionManager
        from src.views.dashboard import DashboardView

        monkeypatch.setattr("src.auth.session_manager.SESSION_DIR", tmp_path)
        monkeypatch.setattr("src.auth.session_manager.SESSION_FILE", tmp_path / "s.pickle")
        monkeypatch.setattr("src.data.cache.CACHE_DB", tmp_path / "cache.db")
        monkeypatch.setattr("src.data.history.HISTORY_DB", tmp_path / "history.db")

        sm = SessionManager()
        dashboard = DashboardView(session_manager=sm, on_logout=lambda: None)
        tabs = [c for c in dashboard.controls if isinstance(c, ft.Tabs)]
        assert len(tabs) == 1, "Dashboard should contain exactly one Tabs widget"


class TestAdjustmentsPanelInit:
    """AdjustmentsPanel instantiation catches API breakage."""

    def test_creates_without_error(self):
        from src.views.adjustments import AdjustmentsPanel

        panel = AdjustmentsPanel(recurring_items=[], on_change=lambda: None)
        assert isinstance(panel, ft.Column)


class TestScrollableColumnLayout:
    """Catch layout issues: expand=True inside scrollable columns causes overlap."""

    @patch("src.auth.session_manager.keyring")
    def test_no_expand_in_scrollable_dashboard(self, mock_keyring, tmp_path: Path, monkeypatch):
        from src.auth.session_manager import SessionManager
        from src.views.dashboard import DashboardView

        monkeypatch.setattr("src.auth.session_manager.SESSION_DIR", tmp_path)
        monkeypatch.setattr("src.auth.session_manager.SESSION_FILE", tmp_path / "s.pickle")
        monkeypatch.setattr("src.data.cache.CACHE_DB", tmp_path / "cache.db")
        monkeypatch.setattr("src.data.history.HISTORY_DB", tmp_path / "history.db")

        sm = SessionManager()
        dashboard = DashboardView(session_manager=sm, on_logout=lambda: None)

        if dashboard.scroll:
            for i, control in enumerate(dashboard.controls):
                expand = getattr(control, "expand", None)
                assert not expand, (
                    f"dashboard.controls[{i}] ({type(control).__name__}) has expand=True "
                    f"inside a scrollable Column — this causes layout overlap"
                )


class TestViewBuildersSmoke:
    """Ensure view builder functions produce valid controls without crashing."""

    def test_build_forecast_chart(self):
        from src.views.chart import build_forecast_chart

        chart = build_forecast_chart(_make_forecast())
        assert chart is not None

    def test_build_transactions_table(self):
        from src.views.transactions_table import build_transactions_table

        table = build_transactions_table(_make_forecast())
        assert isinstance(table, ft.DataTable)

    def test_build_alerts_banner(self):
        from src.views.alerts import build_alerts_banner, generate_alerts

        alerts = generate_alerts(_make_forecast(), safety_threshold=500.0)
        banner = build_alerts_banner(alerts)
        assert isinstance(banner, ft.Column)

    def test_build_accuracy_view_empty(self, tmp_path: Path):
        from src.views.accuracy import build_accuracy_view

        history = ForecastHistory(db_path=tmp_path / "h.db")
        view = build_accuracy_view(history, "acct1")
        assert isinstance(view, ft.Column)
        history.close()

    def test_build_update_banner(self):
        from src.views.update_banner import build_update_banner

        banner = build_update_banner(
            {"version": "0.2.0", "download_url": "https://x.com", "html_url": "https://x.com"}
        )
        assert isinstance(banner, ft.Container)
