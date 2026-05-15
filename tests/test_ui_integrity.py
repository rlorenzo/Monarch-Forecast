"""UI integrity tests — catch Flet API breakage, deprecated usage, and layout issues.

These tests instantiate real UI components with mocked dependencies to catch
runtime errors (wrong kwargs, removed attributes, renamed methods) without
needing a live Flet app window.
"""

import warnings
from pathlib import Path
from unittest.mock import patch

import flet as ft

from tests.factories import make_forecast


class TestNoDeprecationWarnings:
    """Ensure no Flet deprecation warnings fire during module import."""

    def test_all_modules_import_without_deprecation(self):
        import importlib

        modules = [
            "src.main",
            "src.auth.login_view",
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
        mock_keyring.get_password.return_value = None

        with warnings.catch_warnings():
            warnings.filterwarnings("error", category=DeprecationWarning)
            sm = SessionManager()
            LoginView(
                session_manager=sm,
                on_login_success=lambda: None,
                on_demo=lambda: None,
            )
            DashboardView(session_manager=sm, on_logout=lambda: None)
            AdjustmentsPanel(recurring_items=[], on_change=lambda: None)


class TestLoginViewInit:
    """LoginView instantiation catches API breakage (wrong kwargs, removed attrs)."""

    def test_creates_without_error(self, patched_session_manager):
        from src.auth.login_view import LoginView

        view = LoginView(
            session_manager=patched_session_manager,
            on_login_success=lambda: None,
            on_demo=lambda: None,
        )
        assert isinstance(view, ft.Column)
        assert len(view.controls) > 0


class TestDashboardViewInit:
    """DashboardView instantiation catches API breakage."""

    def test_creates_without_error(self, patched_session_manager):
        from src.views.dashboard import DashboardView

        dashboard = DashboardView(session_manager=patched_session_manager, on_logout=lambda: None)
        assert isinstance(dashboard, ft.Column)
        assert len(dashboard.controls) > 0

    def test_has_navigation_rail(self, patched_session_manager):
        from src.views.dashboard import DashboardView
        from src.views.side_nav import SideNav

        dashboard = DashboardView(session_manager=patched_session_manager, on_logout=lambda: None)
        assert dashboard._nav_rail is not None
        assert isinstance(dashboard._nav_rail, SideNav)
        # 3 page destinations — Refresh moved out of the destinations list
        # into its own action row with the timestamp tucked underneath.
        assert len(dashboard._nav_rail._destinations) == 3


class TestIconPathResolution:
    """``_resolve_icon_path`` must always return something usable.

    Returning an empty string would leave the nav rail without a logo in
    packaged distributions where ``__file__`` doesn't resolve the dev-tree
    asset path. The relative ``assets/icon_nav.png`` fallback is what
    Flet's bundled asset server serves in that mode.
    """

    def test_resolves_to_data_uri_in_dev_tree(self):
        from src.views.dashboard import _resolve_icon_path

        result = _resolve_icon_path()
        # In the dev tree the asset exists, so we embed it as a data URI.
        assert result.startswith("data:image/png;base64,"), result[:40]

    def test_falls_back_to_relative_path_when_asset_missing(self, monkeypatch, tmp_path):
        """Simulate the packaged-build case where ``__file__`` lands in a
        bundle layout that puts assets out of reach. The function must
        still return a non-empty path so the nav rail renders the logo."""
        import src.views.dashboard as dashboard_module

        # Point Path(__file__) at a tmp location with no sibling assets/.
        # ``Path.resolve()`` is called on the literal __file__ string, so
        # we patch the module's __file__ attribute and force resolution
        # to a directory tree that doesn't contain icon_nav.png.
        fake_file = tmp_path / "src" / "views" / "dashboard.py"
        fake_file.parent.mkdir(parents=True)
        fake_file.write_text("")
        monkeypatch.setattr(dashboard_module, "__file__", str(fake_file))

        result = dashboard_module._resolve_icon_path()
        assert result == "assets/icon_nav.png"


class TestAdjustmentsPanelInit:
    """AdjustmentsPanel instantiation catches API breakage."""

    def test_creates_without_error(self):
        from src.views.adjustments import AdjustmentsPanel

        panel = AdjustmentsPanel(recurring_items=[], on_change=lambda: None)
        assert isinstance(panel, ft.Column)


class TestScrollableColumnLayout:
    """Catch layout issues: expand=True inside scrollable columns causes overlap."""

    def test_no_expand_in_scrollable_content(self, patched_session_manager):
        from src.views.dashboard import DashboardView

        dashboard = DashboardView(session_manager=patched_session_manager, on_logout=lambda: None)

        # Check the scrollable tab content area's children. The content area
        # itself is a Stack (sticky controls + scroll area + loading overlay);
        # the scrollable region lives in `_scroll_area`, a Column with
        # scroll=ScrollMode.AUTO.
        scroll_area = dashboard._scroll_area
        assert scroll_area.scroll is not None
        for i, control in enumerate(scroll_area.controls):
            expand = getattr(control, "expand", None)
            assert not expand, (
                f"_scroll_area.controls[{i}] ({type(control).__name__}) has expand=True "
                f"inside a scrollable Column — this causes layout overlap"
            )


class TestViewBuildersSmoke:
    """Ensure view builder functions produce valid controls without crashing."""

    def test_build_forecast_chart(self):
        from src.views.chart import build_forecast_chart

        chart = build_forecast_chart(make_forecast())
        assert chart is not None

    def test_build_transactions_table(self):
        from src.views.transactions_table import build_transactions_table

        # Editorial day-block ledger is a Column, not a DataTable. The
        # DataTable was replaced when Transactions adopted the paper-and-
        # ink design system (see src/views/transactions_table.py).
        ledger = build_transactions_table(make_forecast())
        assert isinstance(ledger, ft.Column)

    def test_build_alerts_banner(self):
        from src.views.alerts import Alert, build_alerts_banner

        # With alerts present, the banner is a Semantics live region
        # wrapping a Column of alert rows.
        alerts = [Alert(severity="critical", title="Overdraft", message="msg")]
        banner = build_alerts_banner(alerts)
        assert isinstance(banner, ft.Semantics)
        assert banner.live_region is True
        assert isinstance(banner.content, ft.Column)
        # With zero alerts, we return a bare Container (a Semantics with
        # an empty Column would collapse to zero size and Flet rejects
        # that at render time).
        empty = build_alerts_banner([])
        assert isinstance(empty, ft.Container)

    def test_build_update_banner(self):
        from src.views.update_banner import build_update_banner

        banner = build_update_banner(
            {"version": "0.2.0", "download_url": "https://x.com", "html_url": "https://x.com"}
        )
        assert isinstance(banner, ft.Container)
