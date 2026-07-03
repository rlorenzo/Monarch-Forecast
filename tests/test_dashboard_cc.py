"""Tests for the collapsible Credit Cards section on the Adjustments tab.

The CC section defaults to collapsed (PRODUCT.md: "The chart answers
first" — keep Adjustments focused on one-offs and recurring overrides,
since CC payments are auto-estimated). The toggle handler flips state
in place, persisting across forecast rebuilds.

These tests drive ``DashboardView`` directly, so they exercise the
section's lifecycle without needing a live Flet page.
"""

from __future__ import annotations

from typing import Any, cast

import flet as ft

from src.views.dashboard import DashboardView

# The toggle handler accepts ``ft.Event[ft.Container]`` but ignores the
# argument's contents. Cast a None to the expected type at call sites
# rather than constructing a real Flet event each time.
_FAKE_CONTAINER_EVENT: Any = cast(ft.Event[ft.Container], None)


class TestCCSectionDefaults:
    def test_starts_collapsed(self, patched_session_manager):
        dash = DashboardView(session_manager=patched_session_manager, on_logout=lambda: None)
        assert dash._cc_section_expanded is False

    def test_chevron_and_wrapper_unset_before_update_cc_info(self, patched_session_manager):
        # Before _update_cc_info has been called (no CC accounts loaded yet),
        # the section's mutable handles are None.
        dash = DashboardView(session_manager=patched_session_manager, on_logout=lambda: None)
        assert dash._cc_chevron is None
        assert dash._cc_cards_wrapper is None


class TestToggleHandler:
    def test_toggle_with_widgets_present(self, patched_session_manager):
        dash = DashboardView(session_manager=patched_session_manager, on_logout=lambda: None)
        dash._cc_chevron = ft.Icon(ft.Icons.KEYBOARD_ARROW_RIGHT)
        dash._cc_cards_wrapper = ft.Container(visible=False)

        dash._toggle_cc_section(_FAKE_CONTAINER_EVENT)
        assert dash._cc_section_expanded is True
        assert dash._cc_chevron.icon == ft.Icons.KEYBOARD_ARROW_DOWN
        assert dash._cc_cards_wrapper.visible is True

        dash._toggle_cc_section(_FAKE_CONTAINER_EVENT)
        assert dash._cc_section_expanded is False
        assert dash._cc_chevron.icon == ft.Icons.KEYBOARD_ARROW_RIGHT
        assert dash._cc_cards_wrapper.visible is False

    def test_toggle_without_widgets_still_flips_state(self, patched_session_manager):
        # If _update_cc_info hasn't built the chevron yet (e.g. fired
        # during dashboard construction), the toggle should still flip
        # the persisted flag without raising.
        dash = DashboardView(session_manager=patched_session_manager, on_logout=lambda: None)
        dash._toggle_cc_section(_FAKE_CONTAINER_EVENT)
        assert dash._cc_section_expanded is True

    def test_chevron_semantics_label_updates(self, patched_session_manager):
        dash = DashboardView(session_manager=patched_session_manager, on_logout=lambda: None)
        dash._cc_chevron = ft.Icon(
            ft.Icons.KEYBOARD_ARROW_RIGHT,
            semantics_label="Expand credit cards section",
        )
        dash._cc_cards_wrapper = ft.Container(visible=False)
        dash._toggle_cc_section(_FAKE_CONTAINER_EVENT)
        assert dash._cc_chevron.semantics_label == "Collapse credit cards section"
        dash._toggle_cc_section(_FAKE_CONTAINER_EVENT)
        assert dash._cc_chevron.semantics_label == "Expand credit cards section"


class TestUpdateCcInfo:
    def test_no_cc_accounts_clears_container(self, patched_session_manager):
        dash = DashboardView(session_manager=patched_session_manager, on_logout=lambda: None)
        dash._cc_accounts = []
        dash._update_cc_info()
        assert dash.cc_info_container.content is None

    def test_builds_chevron_and_wrapper(self, patched_session_manager):
        dash = DashboardView(session_manager=patched_session_manager, on_logout=lambda: None)
        dash._cc_accounts = [{"id": "cc1", "name": "Test Card", "balance": -100.0}]
        dash._update_cc_info()
        assert dash._cc_chevron is not None
        assert dash._cc_cards_wrapper is not None

    def test_default_collapsed_after_initial_build(self, patched_session_manager):
        dash = DashboardView(session_manager=patched_session_manager, on_logout=lambda: None)
        dash._cc_accounts = [{"id": "cc1", "name": "Test Card", "balance": -100.0}]
        dash._update_cc_info()
        # Default state is collapsed → wrapper hidden, chevron RIGHT.
        assert dash._cc_cards_wrapper is not None
        assert dash._cc_cards_wrapper.visible is False
        assert dash._cc_chevron is not None
        assert dash._cc_chevron.icon == ft.Icons.KEYBOARD_ARROW_RIGHT

    def test_respects_expanded_state_across_rebuilds(self, patched_session_manager):
        dash = DashboardView(session_manager=patched_session_manager, on_logout=lambda: None)
        dash._cc_accounts = [{"id": "cc1", "name": "Test Card", "balance": -100.0}]
        dash._cc_section_expanded = True
        dash._update_cc_info()
        assert dash._cc_cards_wrapper is not None
        assert dash._cc_cards_wrapper.visible is True
        assert dash._cc_chevron is not None
        assert dash._cc_chevron.icon == ft.Icons.KEYBOARD_ARROW_DOWN

    def test_meta_chip_count_reflects_excluded(self, patched_session_manager, tmp_path):
        # When two of three cards are excluded, the section header should
        # advertise "1 of 3 included".
        from src.data.preferences import Preferences

        prefs = Preferences(path=tmp_path / "prefs.json")
        prefs.set_cc_excluded("cc2", excluded=True)
        prefs.set_cc_excluded("cc3", excluded=True)
        dash = DashboardView(
            session_manager=patched_session_manager,
            on_logout=lambda: None,
            preferences=prefs,
        )
        dash._cc_accounts = [
            {"id": "cc1", "name": "Card 1", "balance": -100.0},
            {"id": "cc2", "name": "Card 2", "balance": -200.0},
            {"id": "cc3", "name": "Card 3", "balance": 0.0},
        ]
        dash._update_cc_info()
        # Walk the rendered content for a Text containing the count.
        found = _find_text_containing(dash.cc_info_container.content, "1 of 3")
        assert found, "Expected '1 of 3 included' chip in the CC section header"


def _find_text_containing(control, needle: str) -> bool:
    """Recursively walk a Flet control tree looking for a ``Text``
    whose value contains ``needle``.

    Used to assert on section-header copy without hard-coding the layout
    path — the header is several Container/Row/Column hops deep.
    """
    if control is None:
        return False
    if isinstance(control, ft.Text) and control.value and needle in control.value:
        return True
    for attr in ("content", "controls", "actions", "title", "subtitle", "leading"):
        value = getattr(control, attr, None)
        if value is None:
            continue
        if isinstance(value, list):
            for child in value:
                if _find_text_containing(child, needle):
                    return True
        else:
            if _find_text_containing(value, needle):
                return True
    return False


class TestRunForecastCcStrip:
    """_run_forecast must strip detected recurring CC-payment items ONLY
    for cards that produced an estimate or that the user excluded."""

    def _dash(self, patched_session_manager) -> DashboardView:
        from datetime import date, timedelta

        from src.data.models import RecurringItem

        dash = DashboardView(session_manager=patched_session_manager, on_logout=lambda: None)
        dash._selected_account_id = "chk1"
        dash._checking_accounts = [{"id": "chk1", "name": "Checking", "balance": 1000.0}]
        dash._txn_history = []
        autopay = RecurringItem(
            name="Chase Reserve Autopay",
            amount=-500.0,
            frequency="monthly",
            base_date=date.today() - timedelta(days=10),
            category="Credit Card Payment",
            account_id="chk1",
        )
        dash.adjustments_panel.update_recurring_items([autopay], account_id="chk1")
        return dash

    def _forecast_names(self, dash: DashboardView) -> list[str]:
        assert dash._forecast is not None
        return [t.name for day in dash._forecast.days for t in day.transactions]

    async def test_card_without_estimate_keeps_detected_autopay(self, patched_session_manager):
        dash = self._dash(patched_session_manager)
        # Chase Reserve: billing settings but no charges → no estimate.
        # Amex: no settings → balance-due fallback → estimate emitted.
        dash._cc_accounts = [
            {"id": "cc1", "name": "Chase Reserve", "balance": -500.0},
            {"id": "cc2", "name": "Amex Gold", "balance": -300.0},
        ]
        dash._prefs.set_cc_billing("cc1", due_day=15, close_day=20)

        await dash._run_forecast()

        names = self._forecast_names(dash)
        # A card without an estimate keeps its detected autopay item:
        # stripping on another card's estimate would erase this card's
        # payment from the forecast entirely.
        assert any(n == "Chase Reserve Autopay" for n in names)
        assert any(n.startswith("Amex Gold Payment") for n in names)

    async def test_estimated_card_strips_matching_autopay(self, patched_session_manager):
        dash = self._dash(patched_session_manager)
        dash._cc_accounts = [{"id": "cc1", "name": "Chase Reserve", "balance": -500.0}]
        # No settings, no matching recurring by name→ falls back to
        # balance-due estimate → payment emitted → autopay stripped.
        await dash._run_forecast()

        names = self._forecast_names(dash)
        assert any(n.startswith("Chase Reserve Payment") for n in names)
        assert not any(n == "Chase Reserve Autopay" for n in names)

    async def test_excluded_card_strips_matching_autopay(self, patched_session_manager):
        dash = self._dash(patched_session_manager)
        dash._cc_accounts = [{"id": "cc1", "name": "Chase Reserve", "balance": -500.0}]
        dash._prefs.set_cc_excluded("cc1", excluded=True)

        await dash._run_forecast()

        names = self._forecast_names(dash)
        assert not any(n.startswith("Chase Reserve Payment") for n in names)
        assert not any(n == "Chase Reserve Autopay" for n in names)


class TestNextCcDueDate:
    async def test_settings_only_card_still_yields_expiry_date(self, patched_session_manager):
        from datetime import date

        from src.forecast.credit_cards import _next_month_day

        dash = DashboardView(session_manager=patched_session_manager, on_logout=lambda: None)
        # Billing settings but NO charges in history: the estimator skips
        # such a card unless an override exists, so _next_cc_due_date must
        # inject a placeholder override to recover the settings due date.
        dash._cc_accounts = [{"id": "cc1", "name": "Chase Reserve", "balance": -500.0}]
        dash._txn_history = []
        dash._prefs.set_cc_billing("cc1", due_day=15, close_day=20)

        due = dash._next_cc_due_date("cc1")
        assert due is not None
        assert due.day == 15
        assert due >= date.today()
        assert due == _next_month_day(date.today(), 15) or due > date.today()

    async def test_unknown_card_returns_none(self, patched_session_manager):
        dash = DashboardView(session_manager=patched_session_manager, on_logout=lambda: None)
        dash._cc_accounts = []
        assert dash._next_cc_due_date("nope") is None
