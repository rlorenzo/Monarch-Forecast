"""Tests for ``DashboardView`` synchronous + async event handlers.

Covers the input-driven handlers (account dropdown, forecast-window
slider, safety threshold), the edit-request dispatchers that open
adjustment dialogs, the nav-rail callbacks, and the small async
background tasks (``_check_for_updates``, ``_refresh_accessibility_features``,
``_on_refresh_action``, ``_on_adjustment_change``).

The dashboard's ``self.page`` raises when not mounted to a real Flet
page, so dialog-opening paths are tested with ``PropertyMock`` patched
onto ``ft.BaseControl.page`` (see ``_with_mock_page``).
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

import flet as ft
import pytest

from src.data.models import ForecastTransaction
from src.data.preferences import Preferences
from src.views.dashboard import DashboardView


def _m(obj: Any) -> Any:
    """Cast through ``Any`` so ``ty`` doesn't try to narrow stubbed
    methods back to their declared shapes.
    """
    return obj


@pytest.fixture
def fake_page() -> MagicMock:
    page = MagicMock(spec=ft.Page)
    page.show_dialog = MagicMock()
    page.pop_dialog = MagicMock()
    page.run_task = MagicMock()
    return page


class TestLogout:
    def test_logout_clears_cache_then_calls_callback(self, patched_session_manager, tmp_path):
        from src.data.cache import DataCache

        cache = DataCache(db_path=tmp_path / "c.db")
        cache.set("txn_history:abc:750", [{"amount": 1.0}])
        on_logout = MagicMock()
        dash = DashboardView(
            session_manager=patched_session_manager,
            on_logout=on_logout,
            cache=cache,
            preferences=Preferences(path=tmp_path / "prefs.json"),
        )
        dash._handle_logout()
        assert cache.get("txn_history:abc:750") is None
        on_logout.assert_called_once()
        cache.close()


@pytest.fixture
def dashboard(patched_session_manager, tmp_path: Path):
    prefs = Preferences(path=tmp_path / "prefs.json")
    prefs.set_onboarding_seen(True)
    dash = DashboardView(
        session_manager=patched_session_manager,
        on_logout=MagicMock(),
        preferences=prefs,
    )
    setattr(dash, "_run_task", MagicMock())  # noqa: B010
    setattr(dash, "_register_service", MagicMock())  # noqa: B010
    setattr(dash, "_show_snackbar", MagicMock())  # noqa: B010
    setattr(dash, "_run_forecast", AsyncMock())  # noqa: B010
    # Replace the loading-stage label + overlay's update so the unmounted
    # dashboard doesn't raise when handlers call _set_loading_stage.
    return dash


def _with_mock_page(page: MagicMock):
    """Context manager that makes ``BaseControl.page`` return ``page``."""
    return patch.object(ft.BaseControl, "page", new_callable=PropertyMock, return_value=page)


# ---------------------------------------------------------------------------
# Slider + threshold + account change
# ---------------------------------------------------------------------------


class TestDaysSlider:
    def test_slider_move_updates_label(self, dashboard):
        e = SimpleNamespace(control=SimpleNamespace(value=60))
        _m(dashboard.account_dropdown).update = MagicMock()
        _m(dashboard._days_label).update = MagicMock()
        dashboard._on_days_slider_move(_m(e))
        assert dashboard._days_label.value == "60 days"


@pytest.mark.asyncio
class TestDaysChange:
    async def test_persists_to_prefs_and_runs_forecast(self, dashboard):
        e = SimpleNamespace(control=SimpleNamespace(value=21))
        _m(dashboard._days_label).update = MagicMock()
        await dashboard._on_days_change(_m(e))
        assert dashboard._days_out == 21
        assert dashboard._prefs.forecast_days == 21
        _m(dashboard._run_forecast).assert_awaited()


@pytest.mark.asyncio
class TestThresholdChange:
    async def test_valid_amount_saves(self, dashboard):
        dashboard.threshold_field.value = "1,500"
        _m(dashboard.threshold_field).update = MagicMock()
        await dashboard._on_threshold_change(_m(SimpleNamespace(control=dashboard.threshold_field)))
        assert dashboard._safety_threshold == 1500.0
        assert dashboard._prefs.safety_threshold == 1500.0
        _m(dashboard._show_snackbar).assert_called()
        _m(dashboard._run_forecast).assert_awaited()

    async def test_invalid_amount_shows_error_and_does_not_save(self, dashboard):
        dashboard.threshold_field.value = "not-a-number"
        _m(dashboard.threshold_field).update = MagicMock()
        prior = dashboard._safety_threshold
        await dashboard._on_threshold_change(_m(SimpleNamespace(control=dashboard.threshold_field)))
        # Threshold unchanged; snackbar called with success=False
        assert dashboard._safety_threshold == prior
        snack_calls = _m(dashboard._show_snackbar).call_args_list
        # First call uses success=False
        assert any(c.kwargs.get("success") is False for c in snack_calls)
        _m(dashboard._run_forecast).assert_not_awaited()

    async def test_negative_amount_clamped_to_zero(self, dashboard):
        dashboard.threshold_field.value = "-100"
        _m(dashboard.threshold_field).update = MagicMock()
        await dashboard._on_threshold_change(_m(SimpleNamespace(control=dashboard.threshold_field)))
        assert dashboard._safety_threshold == 0.0

    async def test_blur_commits_too(self, dashboard):
        # Typing a value and clicking away must save without Enter.
        assert dashboard.threshold_field.on_blur == dashboard._on_threshold_change
        assert dashboard.threshold_field.on_submit == dashboard._on_threshold_change

    async def test_unchanged_value_is_a_noop(self, dashboard):
        # Blur fires right after Enter; the second call with the same
        # value must not re-save, re-toast, or re-run the forecast.
        dashboard.threshold_field.value = f"{dashboard._safety_threshold:g}"
        _m(dashboard.threshold_field).update = MagicMock()
        await dashboard._on_threshold_change(_m(SimpleNamespace(control=dashboard.threshold_field)))
        _m(dashboard._show_snackbar).assert_not_called()
        _m(dashboard._run_forecast).assert_not_awaited()

    async def test_non_finite_rejected(self, dashboard):
        dashboard.threshold_field.value = "inf"
        _m(dashboard.threshold_field).update = MagicMock()
        prior = dashboard._safety_threshold
        await dashboard._on_threshold_change(_m(SimpleNamespace(control=dashboard.threshold_field)))
        assert dashboard._safety_threshold == prior
        _m(dashboard._run_forecast).assert_not_awaited()


@pytest.mark.asyncio
class TestAccountChange:
    async def test_persists_selection_and_runs_forecast(self, dashboard):
        # Stub _update_cc_info — not the subject under test, and it would
        # otherwise raise without _cc_accounts data shape.
        setattr(dashboard, "_update_cc_info", MagicMock())  # noqa: B010
        e = SimpleNamespace(control=SimpleNamespace(value="acct-X"))
        await dashboard._on_account_change(_m(e))
        assert dashboard._selected_account_id == "acct-X"
        assert dashboard._prefs.selected_account_id == "acct-X"
        _m(dashboard._run_forecast).assert_awaited()
        _m(dashboard._update_cc_info).assert_called_once()


# ---------------------------------------------------------------------------
# Edit-request dispatchers
# ---------------------------------------------------------------------------


class TestEditDispatchers:
    def test_edit_cc_amount_with_known_cc_opens_dialog(self, dashboard, fake_page):
        dashboard._cc_accounts = [
            {"id": "cc1", "name": "Chase Sapphire", "balance": -500.0},
        ]
        txn = ForecastTransaction(
            date=date(2026, 6, 1),
            name="Chase Sapphire Payment (1/5)",
            amount=-300.0,
            category="Credit Card Payment",
        )
        with _with_mock_page(fake_page):
            dashboard._on_edit_cc_amount_request(txn)
        fake_page.show_dialog.assert_called_once()

    def test_edit_cc_amount_unknown_cc_is_noop(self, dashboard, fake_page):
        dashboard._cc_accounts = [
            {"id": "cc1", "name": "Chase", "balance": -500.0},
        ]
        txn = ForecastTransaction(
            date=date(2026, 6, 1),
            name="Unrelated payment",
            amount=-300.0,
            category="Credit Card Payment",
        )
        with _with_mock_page(fake_page):
            dashboard._on_edit_cc_amount_request(txn)
        fake_page.show_dialog.assert_not_called()

    def test_edit_oneoff_with_known_index_opens_dialog(self, dashboard, fake_page):
        # Seed a one-off in the panel.
        dashboard.adjustments_panel.add_one_off(
            "Car repair", 200.0, date(2026, 6, 1), is_expense=True
        )
        existing = dashboard.adjustments_panel.one_off_transactions[0]
        with _with_mock_page(fake_page):
            dashboard._on_edit_oneoff_request(existing)
        fake_page.show_dialog.assert_called_once()

    def test_edit_oneoff_unknown_is_noop(self, dashboard, fake_page):
        unknown = ForecastTransaction(
            date=date(2026, 6, 1), name="Unknown", amount=-50.0, id="not-here"
        )
        with _with_mock_page(fake_page):
            dashboard._on_edit_oneoff_request(unknown)
        fake_page.show_dialog.assert_not_called()

    def test_open_add_one_off_dialog(self, dashboard, fake_page):
        with _with_mock_page(fake_page):
            dashboard._open_add_one_off_dialog()
        fake_page.show_dialog.assert_called_once()

    def test_edit_recurring_amount_opens_dialog(self, dashboard, fake_page):
        txn = ForecastTransaction(
            date=date(2026, 6, 1),
            name="Spotify",
            amount=-9.99,
            category="Subscription",
            is_recurring=True,
        )
        with _with_mock_page(fake_page):
            dashboard._on_edit_recurring_amount_request(txn)
        fake_page.show_dialog.assert_called_once()


# ---------------------------------------------------------------------------
# _show_snackbar
# ---------------------------------------------------------------------------


class TestShowSnackbar:
    def test_uses_green_for_success(self, dashboard, fake_page):
        # Remove the stubbed _show_snackbar; we want to test the real impl.
        del dashboard._show_snackbar  # type: ignore[attr-defined]
        with _with_mock_page(fake_page):
            dashboard._show_snackbar("Saved", success=True)
        # show_dialog called with a SnackBar
        snack = fake_page.show_dialog.call_args[0][0]
        assert isinstance(snack, ft.SnackBar)
        assert snack.bgcolor == ft.Colors.GREEN_700

    def test_uses_red_for_failure(self, dashboard, fake_page):
        del dashboard._show_snackbar  # type: ignore[attr-defined]
        with _with_mock_page(fake_page):
            dashboard._show_snackbar("Failed", success=False)
        snack = fake_page.show_dialog.call_args[0][0]
        assert snack.bgcolor == ft.Colors.RED_700

    def test_swallows_unmounted_error(self, dashboard):
        # Without a fake page, show_dialog access raises — _show_snackbar
        # should swallow it.
        del dashboard._show_snackbar  # type: ignore[attr-defined]
        dashboard._show_snackbar("hello")  # should not raise


# ---------------------------------------------------------------------------
# Logout + refresh trigger
# ---------------------------------------------------------------------------


class TestLogoutAndRefresh:
    def test_handle_logout_invokes_callback(self, dashboard):
        dashboard._handle_logout()
        _m(dashboard.on_logout).assert_called_once()

    def test_trigger_refresh_schedules_action(self, dashboard):
        dashboard.trigger_refresh()
        _m(dashboard._run_task).assert_called_once_with(dashboard._on_refresh_action)


# ---------------------------------------------------------------------------
# _on_refresh_click (dirty-CC guard)
# ---------------------------------------------------------------------------


class TestOnRefreshClick:
    def test_no_dirty_cc_schedules_refresh(self, dashboard):
        dashboard._on_refresh_click()
        _m(dashboard._run_task).assert_called_with(dashboard._on_refresh_action)

    def test_dirty_cc_opens_warning_instead(self, dashboard, fake_page):
        dashboard._dirty_cc_cards["cc1"] = {
            "save": lambda _s: True,
            "indicator": MagicMock(),
            "name": "Chase",
        }
        with _with_mock_page(fake_page):
            dashboard._on_refresh_click()
        fake_page.show_dialog.assert_called_once()
        _m(dashboard._run_task).assert_not_called()


# ---------------------------------------------------------------------------
# Nav handlers
# ---------------------------------------------------------------------------


class TestOnNavSelect:
    def test_same_index_is_noop(self, dashboard):
        dashboard._on_nav_select(dashboard._current_nav_index)
        _m(dashboard._run_task).assert_not_called()

    def test_dirty_cc_blocks_and_opens_dialog(self, dashboard, fake_page):
        dashboard._dirty_cc_cards["cc1"] = {
            "save": lambda _s: True,
            "indicator": MagicMock(),
            "name": "Chase",
        }
        with _with_mock_page(fake_page):
            dashboard._on_nav_select(1)
        fake_page.show_dialog.assert_called_once()
        assert dashboard._pending_nav_target == 1

    def test_clean_switch_swaps_to_loader_and_schedules_swap(self, dashboard):
        _m(dashboard._scroll_area).update = MagicMock()
        dashboard._on_nav_select(2)
        assert dashboard._current_nav_index == 2
        # Loading placeholder replaced the scroll area's content.
        assert len(dashboard._scroll_area.controls) == 1
        _m(dashboard._run_task).assert_called_once()


class TestProceedPendingNav:
    def test_no_target_is_noop(self, dashboard):
        dashboard._pending_nav_target = None
        # _do_switch_to_tab calls _safe_update; doesn't raise on unmounted.
        dashboard._proceed_pending_nav()
        # Index unchanged.
        assert dashboard._current_nav_index == 0

    def test_target_advances_index(self, dashboard):
        _m(dashboard._scroll_area).update = MagicMock()
        dashboard._pending_nav_target = 2
        dashboard._proceed_pending_nav()
        assert dashboard._current_nav_index == 2
        assert dashboard._pending_nav_target is None


class TestDoSwitchToTab:
    def test_updates_index_and_swaps_content(self, dashboard):
        _m(dashboard._scroll_area).update = MagicMock()
        dashboard._do_switch_to_tab(1)
        assert dashboard._current_nav_index == 1
        assert dashboard._scroll_area.controls[0] is dashboard._tab_pages[1]


# ---------------------------------------------------------------------------
# Focus helpers
# ---------------------------------------------------------------------------


class TestFocusTabEntry:
    def test_overview_targets_account_dropdown(self, dashboard):
        dashboard._focus_tab_entry(0)
        _m(dashboard._run_task).assert_called_with(
            dashboard._focus_control, dashboard.account_dropdown
        )

    def test_transactions_targets_search_field(self, dashboard):
        dashboard._focus_tab_entry(1)
        _m(dashboard._run_task).assert_called_with(
            dashboard._focus_control, dashboard.transactions_view.search_field
        )

    def test_adjustments_targets_oneoff_name(self, dashboard):
        dashboard._focus_tab_entry(2)
        _m(dashboard._run_task).assert_called_with(
            dashboard._focus_control, dashboard.adjustments_panel._oneoff_name
        )

    def test_invalid_index_does_nothing(self, dashboard):
        dashboard._focus_tab_entry(99)
        _m(dashboard._run_task).assert_not_called()


@pytest.mark.asyncio
class TestFocusControl:
    async def test_calls_async_focus_when_available(self, dashboard):
        control = MagicMock()
        control.focus = AsyncMock()
        await dashboard._focus_control(control)
        control.focus.assert_awaited()

    async def test_no_focus_attr_is_noop(self, dashboard):
        # ``ft.Text`` has no ``focus`` — skipped silently.
        control = ft.Text("hi")
        # Hide the focus attribute that ``ft.Text`` may have inherited.
        await dashboard._focus_control(control)
        # No assertions — just verifies no raise.

    async def test_focus_raising_runtime_error_is_swallowed(self, dashboard):
        control = MagicMock()
        control.focus = AsyncMock(side_effect=RuntimeError("not mounted"))
        await dashboard._focus_control(control)  # should not raise


# ---------------------------------------------------------------------------
# Background async lifecycle
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestCheckForUpdates:
    async def test_displays_banner_when_update_available(self, dashboard):
        with patch(
            "src.views.dashboard.check_update_async",
            new=AsyncMock(return_value={"version": "0.9.0", "html_url": "https://x"}),
        ):
            await dashboard._check_for_updates()
        assert dashboard.update_banner_container.content is not None

    async def test_no_update_leaves_banner_empty(self, dashboard):
        with patch(
            "src.views.dashboard.check_update_async",
            new=AsyncMock(return_value=None),
        ):
            await dashboard._check_for_updates()
        assert dashboard.update_banner_container.content is None

    async def test_exception_swallowed(self, dashboard):
        with patch(
            "src.views.dashboard.check_update_async",
            new=AsyncMock(side_effect=RuntimeError("net down")),
        ):
            await dashboard._check_for_updates()  # should not raise


@pytest.mark.asyncio
class TestRefreshAccessibilityFeatures:
    async def test_picks_up_reduce_motion_flag(self, dashboard):
        # Provide a fake SemanticsService that reports reduce_motion=True.
        class FakeService:
            async def get_accessibility_features(self):
                return SimpleNamespace(reduce_motion=True, disable_animations=False)

        with patch(
            "flet.controls.services.semantics_service.SemanticsService",
            new=lambda: FakeService(),  # type: ignore[misc]
        ):
            await dashboard._refresh_accessibility_features()
        assert dashboard._reduce_motion is True

    async def test_disable_animations_also_flips_flag(self, dashboard):
        class FakeService:
            async def get_accessibility_features(self):
                return SimpleNamespace(reduce_motion=False, disable_animations=True)

        with patch(
            "flet.controls.services.semantics_service.SemanticsService",
            new=lambda: FakeService(),  # type: ignore[misc]
        ):
            await dashboard._refresh_accessibility_features()
        assert dashboard._reduce_motion is True

    async def test_exception_swallowed(self, dashboard):
        # Throw inside the import path so the broad-except catches it.
        with patch(
            "flet.controls.services.semantics_service.SemanticsService",
            new=MagicMock(side_effect=RuntimeError("no service")),
        ):
            await dashboard._refresh_accessibility_features()  # should not raise
        # Flag stays at its construction default.
        assert dashboard._reduce_motion is False


@pytest.mark.asyncio
class TestOnRefreshAction:
    async def test_runs_full_refresh_cycle(self, dashboard):
        # Stub the parts that touch external systems.
        dashboard.monarch = MagicMock()
        dashboard.monarch.refresh_accounts = AsyncMock(return_value=True)
        setattr(dashboard, "load_data", AsyncMock())  # noqa: B010
        await dashboard._on_refresh_action()
        dashboard.monarch.refresh_accounts.assert_awaited_once()
        _m(dashboard.load_data).assert_awaited_with(force_refresh=True)


@pytest.mark.asyncio
class TestOnAdjustmentChange:
    async def test_delegates_to_run_forecast(self, dashboard):
        await dashboard._on_adjustment_change()
        _m(dashboard._run_forecast).assert_awaited()


@pytest.mark.asyncio
class TestSwapNavContent:
    async def test_swaps_in_target_page(self, dashboard):
        _m(dashboard._scroll_area).update = MagicMock()
        await dashboard._swap_nav_content(2)
        assert dashboard._scroll_area.controls[0] is dashboard._tab_pages[2]


class TestForecastAccountIds:
    def test_scopes_to_checking_plus_cards(self, patched_session_manager):
        from src.views.dashboard import DashboardView

        dash = DashboardView(patched_session_manager, on_logout=lambda: None)
        dash._checking_accounts = [{"id": "chk1", "name": "Checking", "balance": 100.0}]
        dash._cc_accounts = [{"id": "cc1", "name": "Card", "balance": -50.0}]
        assert dash._forecast_account_ids() == ["chk1", "cc1"]

    def test_none_before_first_load_syncs_everything(self, patched_session_manager):
        from src.views.dashboard import DashboardView

        dash = DashboardView(patched_session_manager, on_logout=lambda: None)
        assert dash._forecast_account_ids() is None
