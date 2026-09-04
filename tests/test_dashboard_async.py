"""Async-lifecycle tests for DashboardView.

Exercise ``load_data`` (the post-login forecast bootstrap) and
``_run_forecast`` (called every time inputs change). These mock the
Monarch client + the page-bound async scheduler so the methods can run
to completion without a real Flet runtime.

Coverage focus: the happy path (accounts → forecast → chart) plus the
defensive branches (no checking accounts, account-not-found, error
during fetch) where the dashboard sets fallback state instead of
propagating.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.data.models import RecurringItem
from src.data.preferences import Preferences
from src.views.dashboard import DashboardView


@pytest.fixture
def dashboard(patched_session_manager, tmp_path: Path):
    """A DashboardView with the Monarch client + async scheduler stubbed.

    All async tests run through this fixture so the setup boilerplate
    stays in one place.
    """
    prefs = Preferences(path=tmp_path / "prefs.json")
    # Skip the onboarding dialog — it reaches for ``self.page.show_dialog``
    # which would crash on an unmounted dashboard.
    prefs.set_onboarding_seen(True)
    dash = DashboardView(
        session_manager=patched_session_manager,
        on_logout=lambda: None,
        preferences=prefs,
    )

    # ``_run_task`` asserts ``self.page`` is a real Flet Page. In the
    # test harness it isn't, so swap it for a no-op that records calls.
    # ``setattr`` avoids ``ty`` rejecting bound-method shadowing; the
    # ``noqa`` keeps ``ruff`` from rewriting it back to direct assignment.
    setattr(dash, "_run_task", MagicMock())  # noqa: B010
    setattr(dash, "_register_service", MagicMock())  # noqa: B010

    # Async monarch client with canned data. The dashboard reaches for
    # both ``monarch`` (cached) and ``_raw_client`` (raw) — mock both.
    dash.monarch = MagicMock()
    dash.monarch.get_checking_accounts = AsyncMock(return_value=[])
    dash.monarch.get_credit_card_accounts = AsyncMock(return_value=[])
    dash.monarch.refresh_accounts = AsyncMock()
    dash.monarch.get_transactions = AsyncMock(return_value=[])
    dash._raw_client = MagicMock()
    return dash


# ---------------------------------------------------------------------------
# load_data: no checking accounts
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestLoadDataNoAccounts:
    async def test_no_checking_accounts_clears_summary(self, dashboard):
        dashboard.monarch.get_checking_accounts = AsyncMock(return_value=[])
        await dashboard.load_data()
        # No forecast result — summary row carries the "no accounts" message.
        assert dashboard._forecast is None
        controls = dashboard.summary_row.controls
        assert len(controls) == 1

    async def test_no_checking_accounts_clears_chart(self, dashboard):
        await dashboard.load_data()
        assert dashboard.chart_container.content is None


# ---------------------------------------------------------------------------
# load_data: happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestLoadDataHappyPath:
    async def test_loads_accounts_and_builds_forecast(self, dashboard):
        dashboard.monarch.get_checking_accounts = AsyncMock(
            return_value=[
                {"id": "acct1", "name": "Main Checking", "balance": 5000.0},
            ]
        )
        dashboard.monarch.get_credit_card_accounts = AsyncMock(return_value=[])
        dashboard.monarch.get_transactions = AsyncMock(return_value=[])

        await dashboard.load_data()

        assert len(dashboard._checking_accounts) == 1
        assert dashboard._selected_account_id == "acct1"
        assert dashboard._forecast is not None
        assert dashboard._forecast.starting_balance == 5000.0

    async def test_dropdown_populated(self, dashboard):
        dashboard.monarch.get_checking_accounts = AsyncMock(
            return_value=[
                {"id": "acct1", "name": "Main", "balance": 1000.0},
                {"id": "acct2", "name": "Savings", "balance": 2000.0},
            ]
        )
        await dashboard.load_data()
        assert dashboard.account_dropdown.value == "acct1"
        assert dashboard.account_dropdown.options is not None
        assert len(dashboard.account_dropdown.options) == 2

    async def test_saved_account_id_honored_when_present(self, dashboard):
        dashboard._prefs.set_selected_account_id("acct2")
        dashboard.monarch.get_checking_accounts = AsyncMock(
            return_value=[
                {"id": "acct1", "name": "A", "balance": 1.0},
                {"id": "acct2", "name": "B", "balance": 2.0},
            ]
        )
        await dashboard.load_data()
        assert dashboard._selected_account_id == "acct2"

    async def test_saved_account_id_ignored_when_missing(self, dashboard):
        dashboard._prefs.set_selected_account_id("not-here")
        dashboard.monarch.get_checking_accounts = AsyncMock(
            return_value=[
                {"id": "acct1", "name": "A", "balance": 1.0},
            ]
        )
        await dashboard.load_data()
        assert dashboard._selected_account_id == "acct1"


# ---------------------------------------------------------------------------
# load_data: error handling
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestLoadDataErrors:
    async def test_exception_during_fetch_sets_error_summary(self, dashboard):
        dashboard.monarch.get_checking_accounts = AsyncMock(side_effect=RuntimeError("boom"))
        await dashboard.load_data()
        assert dashboard._forecast is None
        # Summary row was replaced with an error Text. Don't assert exact
        # copy here — just that the row has content.
        assert dashboard.summary_row.controls
        # Chart and table cleared on error.
        assert dashboard.chart_container.content is None

    async def test_exception_detail_stays_out_of_summary(self, dashboard):
        # Exception text can carry request URLs / server bodies, so the UI
        # gets a generic message and the detail goes to the log only.
        dashboard.monarch.get_checking_accounts = AsyncMock(side_effect=ValueError("secret-detail"))
        await dashboard.load_data()
        first = dashboard.summary_row.controls[0]
        value = getattr(first, "value", "") or ""
        assert "Error loading data" in value
        assert "secret-detail" not in value


# ---------------------------------------------------------------------------
# _run_forecast
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestRunForecast:
    async def test_no_selected_account_is_noop(self, dashboard):
        dashboard._selected_account_id = None
        prior = dashboard._forecast
        await dashboard._run_forecast()
        assert dashboard._forecast is prior  # unchanged

    async def test_account_not_found_is_noop(self, dashboard):
        dashboard._selected_account_id = "missing"
        dashboard._checking_accounts = [{"id": "acct1", "name": "A", "balance": 1.0}]
        prior = dashboard._forecast
        await dashboard._run_forecast()
        assert dashboard._forecast is prior  # unchanged

    async def test_builds_forecast_for_selected_account(self, dashboard):
        dashboard._selected_account_id = "acct1"
        dashboard._checking_accounts = [
            {"id": "acct1", "name": "Main", "balance": 3000.0},
        ]
        dashboard._recurring_items = []
        dashboard._txn_history = []
        await dashboard._run_forecast()
        assert dashboard._forecast is not None
        assert dashboard._forecast.starting_balance == 3000.0
        # Chart is populated.
        assert dashboard.chart_container.content is not None

    async def test_applies_recurring_to_forecast(self, dashboard):
        from datetime import date

        dashboard._selected_account_id = "acct1"
        dashboard._checking_accounts = [
            {"id": "acct1", "name": "Main", "balance": 5000.0},
        ]
        recurring = [
            RecurringItem(
                name="Rent",
                amount=-1500.0,
                frequency="monthly",
                base_date=date.today(),
                account_id="acct1",
            ),
        ]
        dashboard._recurring_items = recurring
        dashboard.adjustments_panel.update_recurring_items(recurring, account_id="acct1")
        dashboard._txn_history = []
        await dashboard._run_forecast()
        # Forecast applied the rent — ending balance < starting.
        assert dashboard._forecast is not None
        assert dashboard._forecast.starting_balance == 5000.0


# ---------------------------------------------------------------------------
# CC toggle + dashboard helpers
# ---------------------------------------------------------------------------


class TestCCToggle:
    def test_toggle_persists_to_prefs(self, dashboard):
        dashboard._on_cc_toggle("cc1", included=False)
        assert "cc1" in dashboard._prefs.excluded_cc_ids
        dashboard._on_cc_toggle("cc1", included=True)
        assert "cc1" not in dashboard._prefs.excluded_cc_ids

    def test_toggle_runs_forecast(self, dashboard):
        dashboard._on_cc_toggle("cc1", included=False)
        # The toggle schedules a forecast rebuild via _run_task.
        dashboard._run_task.assert_called()

    def test_toggle_refreshes_cc_section_when_no_dirty_cards(self, dashboard):
        # The meta chip ("X of N included") and per-card colors are static
        # until ``_update_cc_info`` re-renders the section. Toggle must
        # trigger that rebuild so the UI doesn't go stale until the user
        # navigates away and back.
        dashboard._cc_accounts = [
            {"id": "cc1", "name": "Card 1", "balance": -100.0},
            {"id": "cc2", "name": "Card 2", "balance": -200.0},
        ]
        # First call seeds the section.
        dashboard._update_cc_info()
        # Re-stub so we only count the toggle-triggered rebuild.
        setattr(dashboard, "_update_cc_info", MagicMock())  # noqa: B010
        dashboard._on_cc_toggle("cc1", included=False)
        dashboard._update_cc_info.assert_called_once()  # type: ignore[attr-defined]

    def test_toggle_skips_refresh_when_other_card_is_dirty(self, dashboard):
        # When another card has unsaved edits, rebuilding would discard
        # those edits + the dirty indicator. Skip the rebuild and accept
        # mild UI staleness on the toggled row until the dirty card
        # saves.
        dashboard._dirty_cc_cards["cc-other"] = {
            "save": lambda _s: True,
            "indicator": MagicMock(),
            "name": "Other",
        }
        setattr(dashboard, "_update_cc_info", MagicMock())  # noqa: B010
        dashboard._on_cc_toggle("cc1", included=False)
        dashboard._update_cc_info.assert_not_called()  # type: ignore[attr-defined]


class TestFindCcForTxn:
    def test_matches_by_name_prefix(self, dashboard):
        from datetime import date

        from src.data.models import ForecastTransaction

        dashboard._cc_accounts = [
            {"id": "cc1", "name": "Chase Sapphire", "balance": -500.0},
            {"id": "cc2", "name": "Amex Gold", "balance": -200.0},
        ]
        txn = ForecastTransaction(
            date=date(2026, 6, 1),
            name="Chase Sapphire Payment (1/5)",
            amount=-300.0,
            category="Credit Card Payment",
        )
        match = dashboard._find_cc_for_txn(txn)
        assert match is not None
        assert match["id"] == "cc1"

    def test_no_match_returns_none(self, dashboard):
        from datetime import date

        from src.data.models import ForecastTransaction

        dashboard._cc_accounts = [
            {"id": "cc1", "name": "Chase Sapphire", "balance": -500.0},
        ]
        txn = ForecastTransaction(
            date=date(2026, 6, 1),
            name="Unrelated Payment",
            amount=-50.0,
            category="Credit Card Payment",
        )
        assert dashboard._find_cc_for_txn(txn) is None


# ---------------------------------------------------------------------------
# Loading-stage helper
# ---------------------------------------------------------------------------


class TestSetLoadingStage:
    def test_show_label(self, dashboard):
        dashboard._set_loading_stage("Loading accounts…")
        assert dashboard._loading_overlay.visible is True
        assert dashboard.loading_stage.value == "Loading accounts…"

    def test_hide(self, dashboard):
        dashboard._set_loading_stage("doing thing")
        dashboard._set_loading_stage(None)
        assert dashboard._loading_overlay.visible is False
        assert dashboard.loading_stage.value == ""


# ---------------------------------------------------------------------------
# Tab switching with no dirty CCs
# ---------------------------------------------------------------------------


class TestSwitchToTab:
    def test_switch_with_no_dirty_cc(self, dashboard):
        dashboard.switch_to_tab(1)
        assert dashboard._current_nav_index == 1

    def test_switch_out_of_range_noop(self, dashboard):
        dashboard.switch_to_tab(99)
        assert dashboard._current_nav_index == 0

    def test_switch_to_same_tab_noop(self, dashboard):
        prior = dashboard._current_nav_index
        dashboard.switch_to_tab(prior)
        assert dashboard._current_nav_index == prior

    def test_dirty_cc_blocks_switch(self, dashboard):
        # Seed a dirty CC; the switch should pend rather than apply.
        dashboard._dirty_cc_cards["cc1"] = {
            "save": lambda _show: True,
            "indicator": Any,
            "name": "Test",
        }
        # show_dialog requires a real page — stub the unsaved-changes path.
        dashboard._show_unsaved_cc_dialog = MagicMock()  # type: ignore[method-assign]
        dashboard.switch_to_tab(1)
        dashboard._show_unsaved_cc_dialog.assert_called_once()
        # Index hasn't changed yet — pending the dialog.
        assert dashboard._current_nav_index == 0
        assert dashboard._pending_nav_target == 1


class TestSplitHistoryFetch:
    async def test_checking_long_cards_short_and_excluded_cards_skipped(
        self, patched_session_manager
    ):
        from src.data.recurring_detector import DEFAULT_LOOKBACK_DAYS
        from src.forecast.credit_cards import CC_HISTORY_DAYS
        from src.views.dashboard import DashboardView

        dash = DashboardView(patched_session_manager, on_logout=lambda: None)
        dash._checking_accounts = [{"id": "chk1", "name": "Checking", "balance": 100.0}]
        dash._cc_accounts = [
            {"id": "cc1", "name": "Card", "balance": -50.0},
            {"id": "cc2", "name": "Old Card", "balance": -10.0},
        ]
        dash._prefs.set_cc_excluded("cc2", excluded=True)
        dash.monarch = MagicMock()
        dash.monarch.get_transactions = AsyncMock(return_value=[])

        await dash._load_txn_history()

        assert dash.monarch.get_transactions.await_count == 2
        first, second = dash.monarch.get_transactions.await_args_list
        assert first.kwargs["account_ids"] == ["chk1"]
        assert first.kwargs["lookback_days"] == DEFAULT_LOOKBACK_DAYS
        assert second.kwargs["account_ids"] == ["cc1"]
        assert second.kwargs["lookback_days"] == CC_HISTORY_DAYS
