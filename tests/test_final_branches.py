"""Final branch coverage — the edit-dialog save/reset closures.

The dashboard's ``_on_edit_*_request`` helpers each define a small
``save`` (and optionally ``reset``) closure that the dialog invokes
with the user's new value. These tests open the dialog, find its Save
button, set a field value, and click — exercising the closure end-to-end.

Plus a few stragglers: ``_remove_one_off`` with a Row, ``_update_chart``
no-forecast guard, ``_update_table`` no-forecast guard.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, PropertyMock, patch

import flet as ft
import pytest

from src.data.models import ForecastTransaction, RecurringItem
from src.data.preferences import Preferences
from src.views.dashboard import DashboardView


def _m(obj: Any) -> Any:
    return obj


@pytest.fixture
def fake_page() -> MagicMock:
    page = MagicMock(spec=ft.Page)
    page.show_dialog = MagicMock()
    page.pop_dialog = MagicMock()
    page.run_task = MagicMock()
    return page


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
    setattr(dash, "_show_snackbar", MagicMock())  # noqa: B010
    return dash


def _with_mock_page(page: MagicMock):
    return patch.object(ft.BaseControl, "page", new_callable=PropertyMock, return_value=page)


def _walk(control: Any):
    if control is None:
        return
    yield control
    for attr in ("content", "controls", "actions", "title", "subtitle", "leading"):
        value = getattr(control, attr, None)
        if value is None:
            continue
        if isinstance(value, list):
            for child in value:
                yield from _walk(child)
        else:
            yield from _walk(value)


def _find_field_by_label(dialog: Any, label: str) -> ft.TextField:
    for c in _walk(dialog):
        if isinstance(c, ft.TextField) and c.label == label:
            return c
    raise AssertionError(f"Field {label!r} not found")


def _find_action_on_click(dialog: ft.AlertDialog, label: str):
    for action in dialog.actions or []:
        for c in _walk(action):
            if isinstance(c, ft.Semantics) and c.label == label:
                inner = c.content
                if isinstance(inner, ft.Container) and inner.on_click is not None:
                    return inner.on_click
    return None


# ---------------------------------------------------------------------------
# _on_edit_cc_amount_request save / reset closures
# ---------------------------------------------------------------------------


class TestEditCCAmountClosures:
    def test_save_persists_override_and_reruns_forecast(self, dashboard, fake_page):
        dashboard._cc_accounts = [{"id": "cc1", "name": "Chase", "balance": -500.0}]
        txn = ForecastTransaction(
            date=date(2026, 6, 1),
            name="Chase Payment (1/5)",
            amount=-300.0,
            category="Credit Card Payment",
        )
        with _with_mock_page(fake_page):
            dashboard._on_edit_cc_amount_request(txn)
            dialog = fake_page.show_dialog.call_args[0][0]
            amount_field = _find_field_by_label(dialog, "AMOUNT")
            amount_field.value = "350.0"
            save = _find_action_on_click(dialog, "Save")
            assert save is not None
            try:
                _m(save)(MagicMock())
            except RuntimeError:
                pass
        assert dashboard._prefs.cc_amount_overrides["cc1"] == 350.0
        _m(dashboard._run_task).assert_called_with(dashboard._run_forecast)

    def test_reset_clears_override_and_reruns_forecast(self, dashboard, fake_page):
        dashboard._cc_accounts = [{"id": "cc1", "name": "Chase", "balance": -500.0}]
        # Seed an existing override so the Reset button surfaces.
        dashboard._prefs.set_cc_amount_override("cc1", 999.0)
        txn = ForecastTransaction(
            date=date(2026, 6, 1),
            name="Chase Payment (1/5)",
            amount=-300.0,
            category="Credit Card Payment",
        )
        with _with_mock_page(fake_page):
            dashboard._on_edit_cc_amount_request(txn)
            dialog = fake_page.show_dialog.call_args[0][0]
            reset = _find_action_on_click(dialog, "Reset to original")
            assert reset is not None
            _m(reset)(MagicMock())
        assert "cc1" not in dashboard._prefs.cc_amount_overrides
        _m(dashboard._run_task).assert_called_with(dashboard._run_forecast)

    def test_save_refreshes_cc_section_when_no_dirty_cards(self, dashboard, fake_page):
        # Without ``_update_cc_info`` in the save closure, the
        # Adjustments tab's "Payment amount" field stays stale until
        # the user navigates away and back.
        dashboard._cc_accounts = [{"id": "cc1", "name": "Chase", "balance": -500.0}]
        setattr(dashboard, "_update_cc_info", MagicMock())  # noqa: B010
        txn = ForecastTransaction(
            date=date(2026, 6, 1),
            name="Chase Payment (1/5)",
            amount=-300.0,
            category="Credit Card Payment",
        )
        with _with_mock_page(fake_page):
            dashboard._on_edit_cc_amount_request(txn)
            dialog = fake_page.show_dialog.call_args[0][0]
            _find_field_by_label(dialog, "AMOUNT").value = "350"
            save = _find_action_on_click(dialog, "Save")
            assert save is not None
            try:
                _m(save)(MagicMock())
            except RuntimeError:
                pass
        dashboard._update_cc_info.assert_called_once()  # type: ignore[attr-defined]

    def test_save_skips_refresh_when_other_card_is_dirty(self, dashboard, fake_page):
        dashboard._cc_accounts = [{"id": "cc1", "name": "Chase", "balance": -500.0}]
        dashboard._dirty_cc_cards["cc-other"] = {
            "save": lambda _s: True,
            "indicator": MagicMock(),
            "name": "Other",
        }
        setattr(dashboard, "_update_cc_info", MagicMock())  # noqa: B010
        txn = ForecastTransaction(
            date=date(2026, 6, 1),
            name="Chase Payment (1/5)",
            amount=-300.0,
            category="Credit Card Payment",
        )
        with _with_mock_page(fake_page):
            dashboard._on_edit_cc_amount_request(txn)
            dialog = fake_page.show_dialog.call_args[0][0]
            _find_field_by_label(dialog, "AMOUNT").value = "350"
            save = _find_action_on_click(dialog, "Save")
            assert save is not None
            try:
                _m(save)(MagicMock())
            except RuntimeError:
                pass
        dashboard._update_cc_info.assert_not_called()  # type: ignore[attr-defined]

    def test_reset_refreshes_cc_section_when_no_dirty_cards(self, dashboard, fake_page):
        dashboard._cc_accounts = [{"id": "cc1", "name": "Chase", "balance": -500.0}]
        dashboard._prefs.set_cc_amount_override("cc1", 999.0)
        setattr(dashboard, "_update_cc_info", MagicMock())  # noqa: B010
        txn = ForecastTransaction(
            date=date(2026, 6, 1),
            name="Chase Payment (1/5)",
            amount=-300.0,
            category="Credit Card Payment",
        )
        with _with_mock_page(fake_page):
            dashboard._on_edit_cc_amount_request(txn)
            dialog = fake_page.show_dialog.call_args[0][0]
            reset = _find_action_on_click(dialog, "Reset to original")
            assert reset is not None
            _m(reset)(MagicMock())
        dashboard._update_cc_info.assert_called_once()  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# _on_edit_oneoff_request save closure
# ---------------------------------------------------------------------------


class TestEditOneOffClosure:
    def test_save_updates_one_off(self, dashboard, fake_page):
        # Seed one-off so find_one_off_index returns an index.
        dashboard.adjustments_panel.add_one_off("Old", 100.0, date(2026, 6, 1), is_expense=True)
        existing = dashboard.adjustments_panel.one_off_transactions[0]
        with _with_mock_page(fake_page):
            dashboard._on_edit_oneoff_request(existing)
            dialog = fake_page.show_dialog.call_args[0][0]
            _find_field_by_label(dialog, "DESCRIPTION").value = "Renamed"
            _find_field_by_label(dialog, "AMOUNT").value = "250"
            _find_field_by_label(dialog, "DATE").value = "2026-07-15"
            save = _find_action_on_click(dialog, "Save")
            assert save is not None
            try:
                _m(save)(MagicMock())
            except RuntimeError:
                pass
        updated = dashboard.adjustments_panel.one_off_transactions[0]
        assert updated.name == "Renamed"
        assert updated.amount == -250.0
        assert updated.date == date(2026, 7, 15)


# ---------------------------------------------------------------------------
# _open_add_one_off_dialog save closure
# ---------------------------------------------------------------------------


class TestAddOneOffDialogClosure:
    def test_save_appends_one_off(self, dashboard, fake_page):
        with _with_mock_page(fake_page):
            dashboard._open_add_one_off_dialog()
            dialog = fake_page.show_dialog.call_args[0][0]
            _find_field_by_label(dialog, "DESCRIPTION").value = "Car repair"
            _find_field_by_label(dialog, "AMOUNT").value = "300"
            _find_field_by_label(dialog, "DATE").value = "2026-08-01"
            save = _find_action_on_click(dialog, "Add transaction")
            assert save is not None
            try:
                _m(save)(MagicMock())
            except RuntimeError:
                pass
        offs = dashboard.adjustments_panel.one_off_transactions
        assert len(offs) == 1
        assert offs[0].name == "Car repair"
        assert offs[0].amount == -300.0


# ---------------------------------------------------------------------------
# _on_edit_recurring_amount_request save / reset closures
# ---------------------------------------------------------------------------


class TestEditRecurringClosures:
    def test_save_applies_signed_override(self, dashboard, fake_page):
        # Drive the dashboard.adjustments_panel to know about an item.
        dashboard.adjustments_panel.update_recurring_items(
            [
                RecurringItem(
                    name="Rent",
                    amount=-1500.0,
                    frequency="monthly",
                    base_date=date(2026, 1, 1),
                ),
            ],
            account_id="",
        )
        txn = ForecastTransaction(
            date=date(2026, 6, 1),
            name="Rent",
            amount=-1500.0,
            category="Housing",
            is_recurring=True,
        )
        with _with_mock_page(fake_page):
            dashboard._on_edit_recurring_amount_request(txn)
            dialog = fake_page.show_dialog.call_args[0][0]
            _find_field_by_label(dialog, "AMOUNT").value = "1800"
            save = _find_action_on_click(dialog, "Save")
            assert save is not None
            try:
                _m(save)(MagicMock())
            except RuntimeError:
                pass
        # is_expense=True → signed negative.
        assert dashboard._prefs.amount_overrides["Rent"] == -1800.0
        _m(dashboard._run_task).assert_called_with(dashboard._run_forecast)

    def test_reset_clears_override(self, dashboard, fake_page):
        dashboard._prefs.set_amount_override("Rent", -1800.0)
        dashboard.adjustments_panel.update_recurring_items(
            [
                RecurringItem(
                    name="Rent",
                    amount=-1500.0,
                    frequency="monthly",
                    base_date=date(2026, 1, 1),
                ),
            ],
            account_id="",
        )
        txn = ForecastTransaction(
            date=date(2026, 6, 1),
            name="Rent",
            amount=-1500.0,
            category="Housing",
            is_recurring=True,
        )
        with _with_mock_page(fake_page):
            dashboard._on_edit_recurring_amount_request(txn)
            dialog = fake_page.show_dialog.call_args[0][0]
            reset = _find_action_on_click(dialog, "Reset to original")
            assert reset is not None
            _m(reset)(MagicMock())
        assert "Rent" not in dashboard._prefs.amount_overrides


# ---------------------------------------------------------------------------
# Stragglers: _update_chart / _update_table no-forecast guards
# ---------------------------------------------------------------------------


class TestUpdateChartGuard:
    def test_no_forecast_returns_early(self, dashboard):
        dashboard._forecast = None
        # Should not raise, and chart_container.content stays whatever it was.
        prior = dashboard.chart_container.content
        dashboard._update_chart()
        assert dashboard.chart_container.content is prior


class TestUpdateTableGuard:
    def test_no_forecast_returns_early(self, dashboard):
        dashboard._forecast = None
        # No-op — transactions view's clear() / set_forecast() aren't called.
        # We can confirm the call is skipped by patching set_forecast.
        dashboard.transactions_view.set_forecast = MagicMock()  # type: ignore[method-assign]
        dashboard._update_table()
        _m(dashboard.transactions_view.set_forecast).assert_not_called()


# ---------------------------------------------------------------------------
# AdjustmentsPanel._remove_one_off with a row spinner swap
# ---------------------------------------------------------------------------


class TestRemoveOneOffWithRow:
    def test_swaps_spinner_into_row(self, tmp_path: Path):
        from src.views.adjustments import AdjustmentsPanel

        prefs = Preferences(path=tmp_path / "p.json")
        panel = AdjustmentsPanel(recurring_items=[], on_change=lambda: None, preferences=prefs)
        panel.add_one_off("X", 100.0, date(2026, 6, 1), is_expense=True)
        # Build a fake row holding the delete pencil as its last control.
        row = ft.Row([ft.Text("placeholder"), ft.IconButton(icon=ft.Icons.DELETE_OUTLINE)])
        # Stub the unmounted row.update.
        _m(row).update = MagicMock()
        panel._remove_one_off(0, row)
        # The last control was replaced by a ProgressRing — the spinner
        # swap-in. Verify by type.
        assert isinstance(row.controls[-1], ft.ProgressRing)
        # One-off was removed.
        assert panel.one_off_transactions == []
