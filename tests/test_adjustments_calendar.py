"""Tests for the calendar handler closures inside Adjustments.

The one-off dialogs (``show_add_one_off_dialog`` /
``show_edit_one_off_dialog``) and the inline panel form all expose:

- a typed-date handler (``on_date_typed``) that canonicalizes the
  TextField value to ``YYYY-MM-DD`` once it parses;
- a calendar-icon click handler (``open_calendar``) that pops the
  ``show_calendar_popover`` modal seeded with the current value;
- an ``on_calendar_pick`` callback that updates the visible field
  when a date cell is tapped.

These live as closures inside the function bodies. Reach them by
finding the date TextField + calendar IconButton in the rendered
dialog/panel and invoking their handlers directly.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, PropertyMock, patch

import flet as ft
import pytest

from src.data.models import ForecastTransaction
from src.data.preferences import Preferences
from src.views.adjustments import (
    AdjustmentsPanel,
    show_add_one_off_dialog,
    show_edit_one_off_dialog,
)


def _m(obj: Any) -> Any:
    return obj


def _make_page() -> MagicMock:
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


def _find_field_by_label(dialog: Any, label: str) -> ft.TextField | None:
    for c in _walk(dialog):
        if isinstance(c, ft.TextField) and c.label == label:
            return c
    return None


def _find_calendar_icon_button(dialog: Any) -> ft.IconButton | None:
    """The calendar affordance is an IconButton(icon=CALENDAR_MONTH)
    wrapped in ``ft.Semantics(label="Open calendar to pick date")``.
    """
    for c in _walk(dialog):
        if isinstance(c, ft.Semantics) and c.label == "Open calendar to pick date":
            inner = c.content
            if isinstance(inner, ft.IconButton):
                return inner
    return None


# ---------------------------------------------------------------------------
# Add-one-off dialog
# ---------------------------------------------------------------------------


class TestAddOneOffDateHandlers:
    def test_typed_date_canonicalises_value(self):
        page = _make_page()
        show_add_one_off_dialog(page, on_save=MagicMock())
        dialog = page.show_dialog.call_args[0][0]
        date_field = _find_field_by_label(dialog, "DATE")
        assert date_field is not None
        # User types in a non-canonical format; on_submit canonicalises.
        date_field.value = "Jan 15, 2026"
        _m(date_field).update = MagicMock()
        _m(date_field.on_submit)(MagicMock())
        assert date_field.value == "2026-01-15"

    def test_typed_unparseable_date_leaves_field_alone(self):
        page = _make_page()
        show_add_one_off_dialog(page, on_save=MagicMock())
        dialog = page.show_dialog.call_args[0][0]
        date_field = _find_field_by_label(dialog, "DATE")
        assert date_field is not None
        date_field.value = "garbage"
        _m(date_field).update = MagicMock()
        _m(date_field.on_submit)(MagicMock())
        # Field stayed as-is.
        assert date_field.value == "garbage"

    def test_on_blur_also_canonicalises(self):
        page = _make_page()
        show_add_one_off_dialog(page, on_save=MagicMock())
        dialog = page.show_dialog.call_args[0][0]
        date_field = _find_field_by_label(dialog, "DATE")
        assert date_field is not None
        date_field.value = "12/25/2026"
        _m(date_field).update = MagicMock()
        _m(date_field.on_blur)(MagicMock())
        assert date_field.value == "2026-12-25"

    def test_calendar_button_opens_popover(self):
        page = _make_page()
        show_add_one_off_dialog(page, on_save=MagicMock())
        dialog = page.show_dialog.call_args[0][0]
        cal_btn = _find_calendar_icon_button(dialog)
        assert cal_btn is not None
        with patch("src.views.adjustments.show_calendar_popover") as mock_popover:
            _m(cal_btn.on_click)(MagicMock())
        mock_popover.assert_called_once()
        # Verify the popover was seeded with the current date-field value.
        kwargs = mock_popover.call_args.kwargs
        date_field = _find_field_by_label(dialog, "DATE")
        assert date_field is not None
        expected = date.fromisoformat(date_field.value or "")
        assert kwargs["initial_date"] == expected

    def test_calendar_button_falls_back_to_picked_date_for_bad_input(self):
        page = _make_page()
        show_add_one_off_dialog(page, on_save=MagicMock())
        dialog = page.show_dialog.call_args[0][0]
        date_field = _find_field_by_label(dialog, "DATE")
        assert date_field is not None
        # Default value is today + 7 days. Corrupt the field.
        date_field.value = "garbage"
        cal_btn = _find_calendar_icon_button(dialog)
        assert cal_btn is not None
        with patch("src.views.adjustments.show_calendar_popover") as mock_popover:
            _m(cal_btn.on_click)(MagicMock())
        # Popover opens at the previously picked date (today + 7), not crashes.
        kwargs = mock_popover.call_args.kwargs
        assert isinstance(kwargs["initial_date"], date)

    def test_calendar_pick_updates_field_value(self):
        page = _make_page()
        show_add_one_off_dialog(page, on_save=MagicMock())
        dialog = page.show_dialog.call_args[0][0]
        date_field = _find_field_by_label(dialog, "DATE")
        assert date_field is not None
        _m(date_field).update = MagicMock()
        cal_btn = _find_calendar_icon_button(dialog)
        assert cal_btn is not None
        # Capture the on_pick callback passed to show_calendar_popover.
        captured: dict[str, Any] = {}
        with patch(
            "src.views.adjustments.show_calendar_popover",
            side_effect=lambda *args, **kwargs: captured.update(kwargs),
        ):
            _m(cal_btn.on_click)(MagicMock())
        on_pick = captured["on_pick"]
        on_pick(date(2026, 8, 22))
        assert date_field.value == "2026-08-22"


# ---------------------------------------------------------------------------
# Edit-one-off dialog
# ---------------------------------------------------------------------------


class TestEditOneOffDateHandlers:
    def _setup(self):
        page = _make_page()
        existing = ForecastTransaction(
            date=date(2026, 6, 1),
            name="Original",
            amount=-200.0,
            category="Adjustment",
            id="abc",
        )
        show_edit_one_off_dialog(page, existing, on_save=MagicMock())
        return page, page.show_dialog.call_args[0][0]

    def test_typed_date_canonicalises(self):
        _page, dialog = self._setup()
        date_field = _find_field_by_label(dialog, "DATE")
        assert date_field is not None
        date_field.value = "07/15/2026"
        _m(date_field).update = MagicMock()
        _m(date_field.on_submit)(MagicMock())
        assert date_field.value == "2026-07-15"

    def test_calendar_pick_updates_field_value(self):
        _page, dialog = self._setup()
        date_field = _find_field_by_label(dialog, "DATE")
        assert date_field is not None
        _m(date_field).update = MagicMock()
        cal_btn = _find_calendar_icon_button(dialog)
        assert cal_btn is not None
        captured: dict[str, Any] = {}
        with patch(
            "src.views.adjustments.show_calendar_popover",
            side_effect=lambda *args, **kwargs: captured.update(kwargs),
        ):
            _m(cal_btn.on_click)(MagicMock())
        captured["on_pick"](date(2026, 11, 1))
        assert date_field.value == "2026-11-01"


# ---------------------------------------------------------------------------
# Inline one-off form on the AdjustmentsPanel
# ---------------------------------------------------------------------------


@pytest.fixture
def panel(tmp_path: Path) -> AdjustmentsPanel:
    prefs = Preferences(path=tmp_path / "prefs.json")
    return AdjustmentsPanel(recurring_items=[], on_change=lambda: None, preferences=prefs)


class TestInlineOneOffDateHandlers:
    def test_on_oneoff_calendar_pick_updates_field(self, panel):
        _m(panel._oneoff_date_display).update = MagicMock()
        panel._on_oneoff_calendar_pick(date(2026, 10, 1))
        assert panel._oneoff_picked_date == date(2026, 10, 1)
        assert panel._oneoff_date_display.value == "2026-10-01"

    def test_on_oneoff_date_typed_canonicalises(self, panel):
        _m(panel._oneoff_date_display).update = MagicMock()
        panel._oneoff_date_display.value = "Jan 05, 2026"
        panel._on_oneoff_date_typed(MagicMock())
        assert panel._oneoff_date_display.value == "2026-01-05"
        assert panel._oneoff_picked_date == date(2026, 1, 5)

    def test_on_oneoff_date_typed_invalid_leaves_value(self, panel):
        _m(panel._oneoff_date_display).update = MagicMock()
        panel._oneoff_date_display.value = "not-a-date"
        panel._on_oneoff_date_typed(MagicMock())
        # Value untouched; picked_date untouched.
        assert panel._oneoff_date_display.value == "not-a-date"

    def test_open_oneoff_calendar_uses_typed_value(self, panel):
        # ``self.page`` raises on an unmounted panel — bypass via PropertyMock.
        fake_page = MagicMock(spec=ft.Page)
        panel._oneoff_date_display.value = "2027-03-14"
        with (
            patch.object(ft.BaseControl, "page", new_callable=PropertyMock, return_value=fake_page),
            patch("src.views.adjustments.show_calendar_popover") as mock_popover,
        ):
            panel._open_oneoff_calendar(MagicMock())
        kwargs = mock_popover.call_args.kwargs
        assert kwargs["initial_date"] == date(2027, 3, 14)

    def test_open_oneoff_calendar_falls_back_to_picked_date(self, panel):
        fake_page = MagicMock(spec=ft.Page)
        panel._oneoff_picked_date = date(2026, 9, 1)
        panel._oneoff_date_display.value = "garbage"
        with (
            patch.object(ft.BaseControl, "page", new_callable=PropertyMock, return_value=fake_page),
            patch("src.views.adjustments.show_calendar_popover") as mock_popover,
        ):
            panel._open_oneoff_calendar(MagicMock())
        kwargs = mock_popover.call_args.kwargs
        assert kwargs["initial_date"] == date(2026, 9, 1)

    def test_open_oneoff_calendar_locks_range_to_year(self, panel):
        fake_page = MagicMock(spec=ft.Page)
        with (
            patch.object(ft.BaseControl, "page", new_callable=PropertyMock, return_value=fake_page),
            patch("src.views.adjustments.show_calendar_popover") as mock_popover,
        ):
            panel._open_oneoff_calendar(MagicMock())
        kwargs = mock_popover.call_args.kwargs
        assert kwargs["first_date"] == date.today()
        assert kwargs["last_date"] == date.today() + timedelta(days=365)


# ---------------------------------------------------------------------------
# _schedule_focus helper
# ---------------------------------------------------------------------------


class TestScheduleFocus:
    def test_with_focus_method_schedules_via_run_task(self):
        from src.views.adjustments import _schedule_focus

        page = _make_page()
        control = MagicMock()
        control.focus = MagicMock()
        _schedule_focus(page, control)
        page.run_task.assert_called_once()

    def test_no_focus_method_is_noop(self):
        from src.views.adjustments import _schedule_focus

        page = _make_page()
        # Use a real ft.Container which has no async focus method.
        control = ft.Container()
        _schedule_focus(page, control)
        page.run_task.assert_not_called()

    def test_base_page_is_skipped(self):
        from src.views.adjustments import _schedule_focus

        # ``ft.BasePage`` is the headless variant — ``_schedule_focus``
        # must return early because there's no event loop to schedule
        # against. Without an early-return ``BasePage`` has no
        # ``run_task`` and the call would raise AttributeError.
        base_page = MagicMock(spec=ft.BasePage)
        control = MagicMock()
        control.focus = MagicMock()
        _schedule_focus(base_page, control)  # should not raise
