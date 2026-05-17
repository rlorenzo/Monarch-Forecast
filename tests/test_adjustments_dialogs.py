"""Validation tests for the Adjustments dialogs.

``show_amount_edit_dialog``, ``show_add_one_off_dialog``, and
``show_edit_one_off_dialog`` all live as closures inside the dialog
builders — invoke them by walking the rendered dialog tree, finding the
primary action button's ``on_click`` (a Container nested inside the
coral_button's Semantics wrapper), and calling it.

Validation failures call ``error_text.update()``, which raises
RuntimeError when the control isn't mounted. That's expected — the
value assignment happens *before* the raise, so we wrap the call and
inspect ``error_text.value`` afterward.
"""

from __future__ import annotations

from datetime import date
from typing import Any
from unittest.mock import MagicMock

import flet as ft

from src.data.models import ForecastTransaction
from src.views.adjustments import (
    show_add_one_off_dialog,
    show_amount_edit_dialog,
    show_edit_one_off_dialog,
)


def _make_page() -> MagicMock:
    """A MagicMock Page that satisfies the dialog signature.

    The dialog builders only call ``page.show_dialog(d)`` and
    ``page.pop_dialog()`` — both captured here. ``page.run_task`` is
    needed by ``_schedule_focus`` and accepts a coroutine factory.
    """
    page = MagicMock(spec=ft.Page)
    page.show_dialog = MagicMock()
    page.pop_dialog = MagicMock()
    page.run_task = MagicMock()
    return page


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


def _find_action_on_click(dialog: ft.AlertDialog, label: str):
    """Return the ``on_click`` of the editorial button labeled ``label``.

    Editorial buttons (``coral_button`` / ``ghost_button`` / ``ink_button``)
    wrap a Container with the click handler inside an ``ft.Semantics``
    node labeled with the button text. Match on that label.
    """
    for action in dialog.actions or []:
        for c in _walk(action):
            if isinstance(c, ft.Semantics) and c.label == label:
                inner = c.content
                if isinstance(inner, ft.Container) and inner.on_click is not None:
                    return inner.on_click
    return None


def _find_field_by_label(dialog: ft.AlertDialog, label: str) -> ft.TextField | None:
    for c in _walk(dialog):
        if isinstance(c, ft.TextField) and c.label == label:
            return c
    return None


def _field(dialog: ft.AlertDialog, label: str) -> ft.TextField:
    """Find a TextField by label or assert. Lets tests assign to ``.value``
    without having to narrow ``Optional`` at every call site (``ty`` doesn't
    honor ``# type: ignore``).
    """
    field = _find_field_by_label(dialog, label)
    assert field is not None, f"Field {label!r} not found in dialog"
    return field


def _find_error_text(dialog: ft.AlertDialog) -> ft.Text | None:
    """The error Text sits inside a live-region Semantics wrapper at the
    bottom of the dialog content column.
    """
    for c in _walk(dialog):
        if isinstance(c, ft.Semantics) and c.live_region is True:
            inner = c.content
            if isinstance(inner, ft.Container) and isinstance(inner.content, ft.Text):
                return inner.content
    return None


def _click(handler, _e: Any = None) -> None:
    """Call a click handler, swallowing the RuntimeError that the inner
    ``.update()`` raises on unmounted controls.
    """
    try:
        handler(_e)
    except RuntimeError:
        pass


# ---------------------------------------------------------------------------
# show_amount_edit_dialog
# ---------------------------------------------------------------------------


class TestAmountEditDialog:
    def test_save_with_valid_amount_calls_on_save_and_pops(self):
        page = _make_page()
        saves: list[float] = []
        show_amount_edit_dialog(
            page,
            title="Edit",
            subtitle="Test",
            current_amount=100.0,
            on_save=lambda v: saves.append(v),
        )
        dialog = page.show_dialog.call_args[0][0]
        amount_field = _find_field_by_label(dialog, "AMOUNT")
        assert amount_field is not None
        amount_field.value = "150.50"
        save = _find_action_on_click(dialog, "Save")
        assert save is not None
        _click(save)
        assert saves == [150.50]
        page.pop_dialog.assert_called_once()

    def test_invalid_amount_sets_error_and_does_not_save(self):
        page = _make_page()
        saves: list[float] = []
        show_amount_edit_dialog(
            page,
            title="Edit",
            subtitle="Test",
            current_amount=100.0,
            on_save=lambda v: saves.append(v),
        )
        dialog = page.show_dialog.call_args[0][0]
        amount_field = _find_field_by_label(dialog, "AMOUNT")
        error_text = _find_error_text(dialog)
        assert amount_field is not None and error_text is not None
        amount_field.value = "not a number"
        save = _find_action_on_click(dialog, "Save")
        assert save is not None
        _click(save)
        assert saves == []
        assert error_text.value == "Enter a valid number."
        page.pop_dialog.assert_not_called()

    def test_non_positive_amount_rejected(self):
        page = _make_page()
        saves: list[float] = []
        show_amount_edit_dialog(
            page,
            title="Edit",
            subtitle="Test",
            current_amount=100.0,
            on_save=lambda v: saves.append(v),
        )
        dialog = page.show_dialog.call_args[0][0]
        amount_field = _find_field_by_label(dialog, "AMOUNT")
        error_text = _find_error_text(dialog)
        assert amount_field is not None and error_text is not None
        amount_field.value = "0"
        save = _find_action_on_click(dialog, "Save")
        assert save is not None
        _click(save)
        assert saves == []
        assert error_text.value == "Amount must be greater than 0."

    def test_amount_with_dollar_sign_and_comma_normalised(self):
        page = _make_page()
        saves: list[float] = []
        show_amount_edit_dialog(
            page,
            title="Edit",
            subtitle="Test",
            current_amount=100.0,
            on_save=lambda v: saves.append(v),
        )
        dialog = page.show_dialog.call_args[0][0]
        amount_field = _find_field_by_label(dialog, "AMOUNT")
        assert amount_field is not None
        amount_field.value = "$1,234.56"
        save = _find_action_on_click(dialog, "Save")
        assert save is not None
        _click(save)
        assert saves == [1234.56]

    def test_reset_button_appears_when_on_reset_provided(self):
        page = _make_page()
        reset_called: list[int] = []
        show_amount_edit_dialog(
            page,
            title="Edit",
            subtitle="Test",
            current_amount=100.0,
            on_save=lambda _v: None,
            on_reset=lambda: reset_called.append(1),
        )
        dialog = page.show_dialog.call_args[0][0]
        # Reset action button has label "Reset to original".
        reset = _find_action_on_click(dialog, "Reset to original")
        assert reset is not None
        _click(reset)
        assert reset_called == [1]

    def test_reset_button_absent_when_no_reset(self):
        page = _make_page()
        show_amount_edit_dialog(
            page,
            title="Edit",
            subtitle="Test",
            current_amount=100.0,
            on_save=lambda _v: None,
        )
        dialog = page.show_dialog.call_args[0][0]
        assert _find_action_on_click(dialog, "Reset to original") is None

    def test_cancel_pops_without_saving(self):
        page = _make_page()
        saves: list[float] = []
        show_amount_edit_dialog(
            page,
            title="Edit",
            subtitle="Test",
            current_amount=100.0,
            on_save=lambda v: saves.append(v),
        )
        dialog = page.show_dialog.call_args[0][0]
        cancel = _find_action_on_click(dialog, "Cancel")
        assert cancel is not None
        _click(cancel)
        assert saves == []
        page.pop_dialog.assert_called_once()


# ---------------------------------------------------------------------------
# show_add_one_off_dialog
# ---------------------------------------------------------------------------


class TestAddOneOffDialog:
    def _setup(self):
        page = _make_page()
        saves: list[tuple[str, float, date, bool]] = []
        show_add_one_off_dialog(
            page,
            on_save=lambda name, amt, d, is_exp: saves.append((name, amt, d, is_exp)),
        )
        dialog = page.show_dialog.call_args[0][0]
        return page, dialog, saves

    def test_empty_description_rejected(self):
        _page, dialog, saves = self._setup()
        save = _find_action_on_click(dialog, "Add transaction")
        assert save is not None
        _click(save)
        err = _find_error_text(dialog)
        assert err is not None and err.value == "Description is required."
        assert saves == []

    def test_missing_amount_rejected(self):
        _page, dialog, saves = self._setup()
        _field(dialog, "DESCRIPTION").value = "Car repair"
        save = _find_action_on_click(dialog, "Add transaction")
        assert save is not None
        _click(save)
        err = _find_error_text(dialog)
        assert err is not None and err.value == "Enter a valid number."
        assert saves == []

    def test_negative_amount_rejected(self):
        _page, dialog, saves = self._setup()
        _field(dialog, "DESCRIPTION").value = "Car repair"
        _field(dialog, "AMOUNT").value = "-50"
        save = _find_action_on_click(dialog, "Add transaction")
        assert save is not None
        _click(save)
        err = _find_error_text(dialog)
        assert err is not None and err.value == "Amount must be greater than 0."
        assert saves == []

    def test_invalid_date_rejected(self):
        _page, dialog, saves = self._setup()
        _field(dialog, "DESCRIPTION").value = "Car repair"
        _field(dialog, "AMOUNT").value = "200"
        _field(dialog, "DATE").value = "garbage"
        save = _find_action_on_click(dialog, "Add transaction")
        assert save is not None
        _click(save)
        err = _find_error_text(dialog)
        assert err is not None and err.value == "Enter a valid date (YYYY-MM-DD)."
        assert saves == []

    def test_valid_input_saves_expense(self):
        page, dialog, saves = self._setup()
        _field(dialog, "DESCRIPTION").value = "Car repair"
        _field(dialog, "AMOUNT").value = "200"
        _field(dialog, "DATE").value = "2026-08-01"
        save = _find_action_on_click(dialog, "Add transaction")
        assert save is not None
        _click(save)
        assert saves == [("Car repair", 200.0, date(2026, 8, 1), True)]
        page.pop_dialog.assert_called_once()

    def test_valid_input_saves_income(self):
        _page, dialog, saves = self._setup()
        _field(dialog, "DESCRIPTION").value = "Tax refund"
        _field(dialog, "AMOUNT").value = "1500"
        _field(dialog, "DATE").value = "2026-04-15"
        # Flip the Type dropdown to income.
        for c in _walk(dialog):
            if isinstance(c, ft.Dropdown) and c.label == "TYPE":
                c.value = "income"
                break
        save = _find_action_on_click(dialog, "Add transaction")
        assert save is not None
        _click(save)
        assert saves == [("Tax refund", 1500.0, date(2026, 4, 15), False)]


# ---------------------------------------------------------------------------
# show_edit_one_off_dialog
# ---------------------------------------------------------------------------


class TestEditOneOffDialog:
    def _setup(self, existing: ForecastTransaction | None = None):
        page = _make_page()
        saves: list[tuple[str, float, date]] = []
        existing = existing or ForecastTransaction(
            date=date(2026, 6, 1),
            name="Original",
            amount=-200.0,
            category="Adjustment",
            id="abc",
        )
        show_edit_one_off_dialog(
            page,
            existing=existing,
            on_save=lambda name, amt, d: saves.append((name, amt, d)),
        )
        dialog = page.show_dialog.call_args[0][0]
        return page, dialog, saves

    def test_prefills_existing_values(self):
        _page, dialog, _saves = self._setup()
        desc = _find_field_by_label(dialog, "DESCRIPTION")
        amt = _find_field_by_label(dialog, "AMOUNT")
        dt = _find_field_by_label(dialog, "DATE")
        assert desc is not None and desc.value == "Original"
        assert amt is not None and amt.value == "200.00"
        assert dt is not None and dt.value == "2026-06-01"

    def test_save_updates_fields(self):
        page, dialog, saves = self._setup()
        _field(dialog, "DESCRIPTION").value = "Renamed"
        _field(dialog, "AMOUNT").value = "250"
        _field(dialog, "DATE").value = "2026-07-01"
        save = _find_action_on_click(dialog, "Save")
        assert save is not None
        _click(save)
        assert saves == [("Renamed", 250.0, date(2026, 7, 1))]
        page.pop_dialog.assert_called_once()

    def test_empty_description_rejected(self):
        _page, dialog, saves = self._setup()
        _field(dialog, "DESCRIPTION").value = ""
        save = _find_action_on_click(dialog, "Save")
        assert save is not None
        _click(save)
        err = _find_error_text(dialog)
        assert err is not None and err.value == "Description is required."
        assert saves == []
