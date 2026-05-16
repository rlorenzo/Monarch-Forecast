"""Validation tests for the per-CC billing card (Adjustments tab).

``_build_cc_billing_card`` returns a Column whose header row is the
visible CC entry and whose collapsible body holds three TextFields
(due day / close day / payment amount), a Save button, a dirty
indicator, and a hint line.

The save closure ``save_all`` performs all the validation. To exercise
each branch we build a card, walk the tree to find the Save button's
``on_click`` (which calls ``save_all()`` indirectly) plus each
TextField, and then trigger save with various combinations.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import flet as ft
import pytest

from src.data.preferences import Preferences
from src.views.dashboard import DashboardView


@pytest.fixture
def dashboard(patched_session_manager, tmp_path: Path):
    prefs = Preferences(path=tmp_path / "prefs.json")
    dash = DashboardView(
        session_manager=patched_session_manager,
        on_logout=lambda: None,
        preferences=prefs,
    )
    # Both helpers reach for ``self.page`` which is None on an unmounted
    # dashboard. Stub them to no-ops so the validation branches don't
    # crash on the post-validation snackbar/forecast-rebuild calls.
    # ``setattr`` avoids ``ty`` rejecting bound-method shadowing; the
    # ``noqa`` keeps ``ruff`` from rewriting it back to direct assignment.
    setattr(dash, "_show_snackbar", MagicMock())  # noqa: B010
    setattr(dash, "_run_task", MagicMock())  # noqa: B010
    return dash


def _invoke(callback: Any, *args: Any) -> Any:
    """Dispatch a Flet ``Optional[Callable[..., Any]]`` from a test.

    Taking ``callback: Any`` opts out of the narrowing chase, so the
    call site can pass through without ``# type: ignore``.
    """
    return callback(*args)


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


def _find_field_by_label(card: ft.Control, label: str) -> ft.TextField | None:
    for c in _walk(card):
        if isinstance(c, ft.TextField) and c.label == label:
            return c
    return None


def _field(card: ft.Control, label: str) -> ft.TextField:
    """Like ``_find_field_by_label`` but asserts and unwraps the Optional
    so tests can assign to ``.value`` without per-call narrowing.
    """
    f = _find_field_by_label(card, label)
    assert f is not None, f"Field {label!r} not found"
    return f


def _find_save_handler(card: ft.Control, cc_name: str):
    """``coral_button`` wraps the save handler in
    ``ft.Semantics(label=f"Save billing settings for {cc_name}")``.
    Drill in and return the inner Container's ``on_click``.
    """
    sr_label = f"Save billing settings for {cc_name}"
    for c in _walk(card):
        if isinstance(c, ft.Semantics) and c.label == sr_label:
            inner = c.content
            if isinstance(inner, ft.Container) and inner.on_click is not None:
                return inner.on_click
    return None


def _find_dirty_indicator(card: ft.Control) -> ft.Text | None:
    """The dirty indicator Text carries the literal copy 'Unsaved changes'."""
    for c in _walk(card):
        if isinstance(c, ft.Text) and c.value == "Unsaved changes":
            return c
    return None


def _click(handler, _e: Any = None) -> None:
    try:
        handler(_e)
    except RuntimeError:
        pass


def _build(dashboard: DashboardView, **overrides):
    defaults: dict[str, Any] = dict(
        cc_id="cc1",
        name="Test Card",
        owed=100.0,
        is_excluded=False,
        due_day="",
        close_day="",
        amt_override="",
        is_first=True,
    )
    defaults.update(overrides)
    return dashboard._build_cc_billing_card(**defaults)


class TestCheckboxAbsorbsClicks:
    """The CC checkbox sits inside the clickable header row that toggles
    the card's expand/collapse state. Production code wraps the checkbox
    in a defensive ``Container`` with a no-op ``on_click`` so a tap on
    the checkbox is consumed there rather than bubbling to the row
    toggle. This test pins that absorber in place — without it, every
    include/exclude toggle would also flip the section open/closed.
    """

    def test_checkbox_container_has_noop_on_click(self, dashboard):
        card = _build(dashboard)
        # Find the Checkbox in the card tree.
        for c in _walk(card):
            if isinstance(c, ft.Checkbox):
                checkbox = c
                break
        else:
            raise AssertionError("Checkbox not found in CC billing card")
        # The Checkbox's immediate parent Container must carry its own
        # on_click (the absorber). Walking the tree again to find the
        # Container whose ``content`` is the Checkbox.
        absorber = None
        for c in _walk(card):
            if isinstance(c, ft.Container) and c.content is checkbox:
                absorber = c
                break
        assert absorber is not None
        assert absorber.on_click is not None, (
            "Checkbox cell must have on_click set so taps don't bubble to the "
            "header toggle. Without this, every include/exclude toggle would "
            "also flip the section's expand state."
        )


class TestSavePersistsValidValues:
    def test_save_due_close_and_amount(self, dashboard):
        card = _build(dashboard)
        _field(card, "DUE DAY").value = "15"
        _field(card, "CLOSE DAY").value = "20"
        _field(card, "PAYMENT AMOUNT").value = "250"
        save = _find_save_handler(card, "Test Card")
        assert save is not None
        _click(save)
        billing = dashboard._prefs.cc_billing_settings.get("cc1", {})
        assert billing.get("due_day") == 15
        assert billing.get("close_day") == 20
        assert dashboard._prefs.cc_amount_overrides.get("cc1") == 250.0
        dashboard._show_snackbar.assert_called()  # success snack

    def test_save_empty_amount_clears_override(self, dashboard):
        # Seed an existing override, then save with an empty amount field.
        dashboard._prefs.set_cc_amount_override("cc1", 999.0)
        card = _build(dashboard, amt_override=999.0)
        _field(card, "PAYMENT AMOUNT").value = ""
        save = _find_save_handler(card, "Test Card")
        assert save is not None
        _click(save)
        assert "cc1" not in dashboard._prefs.cc_amount_overrides

    def test_save_only_due_day_infers_close(self, dashboard):
        # Provide due day without close day → save_all should infer close
        # from the default grace period.
        card = _build(dashboard)
        _field(card, "DUE DAY").value = "15"
        save = _find_save_handler(card, "Test Card")
        assert save is not None
        _click(save)
        billing = dashboard._prefs.cc_billing_settings.get("cc1", {})
        assert billing.get("due_day") == 15
        assert isinstance(billing.get("close_day"), int)

    def test_save_only_close_day_infers_due(self, dashboard):
        card = _build(dashboard)
        _field(card, "CLOSE DAY").value = "20"
        save = _find_save_handler(card, "Test Card")
        assert save is not None
        _click(save)
        billing = dashboard._prefs.cc_billing_settings.get("cc1", {})
        assert billing.get("close_day") == 20
        assert isinstance(billing.get("due_day"), int)


class TestSaveValidation:
    def test_invalid_due_day_string(self, dashboard):
        card = _build(dashboard)
        _field(card, "DUE DAY").value = "abc"
        save = _find_save_handler(card, "Test Card")
        assert save is not None
        _click(save)
        dashboard._show_snackbar.assert_called_with("Due day must be a number", success=False)
        assert "cc1" not in dashboard._prefs.cc_billing_settings

    def test_due_day_out_of_range_low(self, dashboard):
        card = _build(dashboard)
        _field(card, "DUE DAY").value = "0"
        save = _find_save_handler(card, "Test Card")
        assert save is not None
        _click(save)
        dashboard._show_snackbar.assert_called_with(
            "Due day must be between 1 and 31", success=False
        )

    def test_due_day_out_of_range_high(self, dashboard):
        card = _build(dashboard)
        _field(card, "DUE DAY").value = "32"
        save = _find_save_handler(card, "Test Card")
        assert save is not None
        _click(save)
        dashboard._show_snackbar.assert_called_with(
            "Due day must be between 1 and 31", success=False
        )

    def test_invalid_close_day_string(self, dashboard):
        card = _build(dashboard)
        _field(card, "CLOSE DAY").value = "xyz"
        save = _find_save_handler(card, "Test Card")
        assert save is not None
        _click(save)
        dashboard._show_snackbar.assert_called_with("Close day must be a number", success=False)

    def test_close_day_out_of_range(self, dashboard):
        card = _build(dashboard)
        _field(card, "CLOSE DAY").value = "99"
        save = _find_save_handler(card, "Test Card")
        assert save is not None
        _click(save)
        dashboard._show_snackbar.assert_called_with(
            "Close day must be between 1 and 31", success=False
        )

    def test_invalid_amount_string(self, dashboard):
        card = _build(dashboard)
        _field(card, "PAYMENT AMOUNT").value = "five hundred"
        save = _find_save_handler(card, "Test Card")
        assert save is not None
        _click(save)
        dashboard._show_snackbar.assert_called_with(
            "Payment amount must be a number", success=False
        )

    def test_zero_amount_rejected(self, dashboard):
        card = _build(dashboard)
        _field(card, "PAYMENT AMOUNT").value = "0"
        save = _find_save_handler(card, "Test Card")
        assert save is not None
        _click(save)
        dashboard._show_snackbar.assert_called_with(
            "Payment amount must be greater than 0", success=False
        )

    def test_amount_with_dollar_sign_normalised(self, dashboard):
        card = _build(dashboard)
        _field(card, "PAYMENT AMOUNT").value = "$1,234.56"
        save = _find_save_handler(card, "Test Card")
        assert save is not None
        _click(save)
        assert dashboard._prefs.cc_amount_overrides.get("cc1") == 1234.56


class TestDirtyState:
    def test_field_change_marks_dirty(self, dashboard):
        card = _build(dashboard)
        due_field = _find_field_by_label(card, "DUE DAY")
        dirty = _find_dirty_indicator(card)
        assert due_field is not None and dirty is not None
        assert dirty.visible is False
        # Simulate user editing the field.
        from types import SimpleNamespace

        _invoke(due_field.on_change, SimpleNamespace(control=due_field))
        assert dirty.visible is True
        assert "cc1" in dashboard._dirty_cc_cards

    def test_successful_save_clears_dirty(self, dashboard):
        card = _build(dashboard)
        due_field = _find_field_by_label(card, "DUE DAY")
        dirty = _find_dirty_indicator(card)
        assert due_field is not None and dirty is not None
        due_field.value = "15"
        # Mark dirty via on_change.
        from types import SimpleNamespace

        _invoke(due_field.on_change, SimpleNamespace(control=due_field))
        assert dirty.visible is True
        # Save → mark_clean() should run.
        save = _find_save_handler(card, "Test Card")
        assert save is not None
        _click(save)
        assert dirty.visible is False
        assert "cc1" not in dashboard._dirty_cc_cards

    def test_validation_failure_leaves_dirty_visible(self, dashboard):
        card = _build(dashboard)
        due_field = _find_field_by_label(card, "DUE DAY")
        dirty = _find_dirty_indicator(card)
        assert due_field is not None and dirty is not None
        due_field.value = "garbage"
        # Mark dirty first.
        from types import SimpleNamespace

        _invoke(due_field.on_change, SimpleNamespace(control=due_field))
        assert dirty.visible is True
        # Save with invalid value → validation fails, dirty stays.
        save = _find_save_handler(card, "Test Card")
        assert save is not None
        _click(save)
        assert dirty.visible is True
        assert "cc1" in dashboard._dirty_cc_cards


class TestSubmitOnEnter:
    def test_enter_key_triggers_save(self, dashboard):
        card = _build(dashboard)
        due_field = _find_field_by_label(card, "DUE DAY")
        assert due_field is not None
        due_field.value = "12"
        from types import SimpleNamespace

        _invoke(due_field.on_submit, SimpleNamespace(control=due_field))
        billing = dashboard._prefs.cc_billing_settings.get("cc1", {})
        assert billing.get("due_day") == 12
