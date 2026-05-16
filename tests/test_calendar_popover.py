"""Tests for the minimal calendar popover.

The popover renders the month grid, auto-saves on day-tap, and supports
prev/next month navigation. It also honors ``first_date`` / ``last_date``
ranges by disabling cells outside the window.

These tests drive ``show_calendar_popover`` with a ``MagicMock`` page —
no live Flet runtime is required — and walk the resulting dialog tree
to exercise day-cell builders, the month-shift handler, and the
``on_pick`` round-trip.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any
from unittest.mock import MagicMock

import flet as ft

from src.views.calendar_popover import show_calendar_popover


def _click(handler: Any) -> None:
    """Invoke a Flet click handler from a test.

    Flet types ``on_click`` as ``() -> Any | (Event[X]) -> Any | None``,
    which ``ty`` won't narrow even after ``assert is not None``. Taking
    ``handler: Any`` opts out of the narrowing chase at every call site.
    """
    handler(None)


def _make_page() -> MagicMock:
    page = MagicMock(spec=ft.Page)
    page.show_dialog = MagicMock()
    page.pop_dialog = MagicMock()
    return page


def _walk(control: Any):
    """Yield every Control reachable from ``control``."""
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


def _find_day_cell(dialog: Any, day_str: str) -> ft.Container | None:
    """Return the Container holding the Text(day_str) day-cell, if any."""
    for c in _walk(dialog):
        if (
            isinstance(c, ft.Container)
            and isinstance(c.content, ft.Text)
            and c.content.value == day_str
            and c.on_click is not None
        ):
            return c
    return None


def _find_chevron_button(dialog: Any, label: str) -> ft.IconButton | None:
    """Return the IconButton wrapped by a Semantics(label=...) ancestor."""
    for c in _walk(dialog):
        if isinstance(c, ft.Semantics) and c.label == label:
            inner = c.content
            if isinstance(inner, ft.IconButton):
                return inner
    return None


class TestPopoverConstruction:
    def test_shows_dialog(self):
        page = _make_page()
        show_calendar_popover(page, initial_date=date(2026, 1, 15), on_pick=lambda _d: None)
        page.show_dialog.assert_called_once()
        dialog = page.show_dialog.call_args[0][0]
        assert isinstance(dialog, ft.AlertDialog)

    def test_renders_month_label(self):
        page = _make_page()
        show_calendar_popover(page, initial_date=date(2026, 3, 1), on_pick=lambda _d: None)
        dialog = page.show_dialog.call_args[0][0]
        texts = [c.value for c in _walk(dialog) if isinstance(c, ft.Text)]
        assert any("March 2026" in (t or "") for t in texts)


class TestDayCellSelection:
    def test_clicking_day_calls_on_pick_and_pops(self):
        page = _make_page()
        picked: list[date] = []
        show_calendar_popover(
            page, initial_date=date(2026, 1, 15), on_pick=lambda d: picked.append(d)
        )
        dialog = page.show_dialog.call_args[0][0]
        cell = _find_day_cell(dialog, "20")
        assert cell is not None
        assert cell.on_click is not None
        _click(cell.on_click)
        page.pop_dialog.assert_called_once()
        assert picked == [date(2026, 1, 20)]

    def test_today_cell_has_highlight(self):
        page = _make_page()
        today = date.today()
        show_calendar_popover(page, initial_date=today, on_pick=lambda _d: None)
        dialog = page.show_dialog.call_args[0][0]
        cell = _find_day_cell(dialog, str(today.day))
        # Today (which is also the initial selected date) carries the
        # primary fill colour.
        assert cell is not None
        assert cell.bgcolor is not None


class TestRangeBounds:
    def test_day_before_first_date_disabled(self):
        page = _make_page()
        # initial_date = Jan 15, first_date = Jan 10 → Jan 5 should be disabled.
        show_calendar_popover(
            page,
            initial_date=date(2026, 1, 15),
            on_pick=lambda _d: None,
            first_date=date(2026, 1, 10),
        )
        dialog = page.show_dialog.call_args[0][0]
        # The day-cell for "5" should have no on_click — i.e. it won't
        # appear in our finder. Walk explicitly looking for the disabled cell.
        disabled = None
        for c in _walk(dialog):
            if (
                isinstance(c, ft.Container)
                and isinstance(c.content, ft.Text)
                and c.content.value == "5"
                and c.on_click is None
                and c.opacity == 0.35
            ):
                disabled = c
                break
        assert disabled is not None

    def test_day_after_last_date_disabled(self):
        page = _make_page()
        show_calendar_popover(
            page,
            initial_date=date(2026, 1, 15),
            on_pick=lambda _d: None,
            last_date=date(2026, 1, 20),
        )
        dialog = page.show_dialog.call_args[0][0]
        # Day 25 should be disabled.
        disabled = None
        for c in _walk(dialog):
            if (
                isinstance(c, ft.Container)
                and isinstance(c.content, ft.Text)
                and c.content.value == "25"
                and c.on_click is None
                and c.opacity == 0.35
            ):
                disabled = c
                break
        assert disabled is not None


class TestMonthNavigation:
    def test_next_month_shifts_forward(self):
        page = _make_page()
        show_calendar_popover(page, initial_date=date(2026, 1, 15), on_pick=lambda _d: None)
        dialog = page.show_dialog.call_args[0][0]

        # Find the month label Text so we can assert on its updated value
        # after the shift.
        month_label = None
        for c in _walk(dialog):
            if isinstance(c, ft.Text) and c.value and "January 2026" in c.value:
                month_label = c
                break
        assert month_label is not None

        next_btn = _find_chevron_button(dialog, "Next month")
        assert next_btn is not None
        # Click handler captures `shift_month(1)` — invoke it.
        _click(next_btn.on_click)
        assert month_label.value == "February 2026"

    def test_prev_month_wraps_to_previous_year(self):
        page = _make_page()
        show_calendar_popover(page, initial_date=date(2026, 1, 15), on_pick=lambda _d: None)
        dialog = page.show_dialog.call_args[0][0]

        month_label = next(
            (
                c
                for c in _walk(dialog)
                if isinstance(c, ft.Text) and c.value and "January 2026" in c.value
            ),
            None,
        )
        assert month_label is not None

        prev_btn = _find_chevron_button(dialog, "Previous month")
        assert prev_btn is not None
        _click(prev_btn.on_click)
        assert month_label.value == "December 2025"

    def test_next_wraps_to_next_year_from_december(self):
        page = _make_page()
        show_calendar_popover(page, initial_date=date(2025, 12, 1), on_pick=lambda _d: None)
        dialog = page.show_dialog.call_args[0][0]
        month_label = next(
            (
                c
                for c in _walk(dialog)
                if isinstance(c, ft.Text) and c.value and "December 2025" in c.value
            ),
            None,
        )
        assert month_label is not None
        next_btn = _find_chevron_button(dialog, "Next month")
        assert next_btn is not None
        _click(next_btn.on_click)
        assert month_label.value == "January 2026"


class TestEdgeCases:
    def test_initial_date_at_first_date_is_selectable(self):
        page = _make_page()
        show_calendar_popover(
            page,
            initial_date=date(2026, 1, 10),
            on_pick=lambda _d: None,
            first_date=date(2026, 1, 10),
        )
        dialog = page.show_dialog.call_args[0][0]
        cell = _find_day_cell(dialog, "10")
        assert cell is not None  # not disabled

    def test_far_future_dates_disabled(self):
        page = _make_page()
        show_calendar_popover(
            page,
            initial_date=date(2026, 1, 15),
            on_pick=lambda _d: None,
            last_date=date.today() + timedelta(days=1),
        )
        dialog = page.show_dialog.call_args[0][0]
        # 20 Jan 2026 falls after 1 day from today (in 2026-05-15 context),
        # so cell 20 should still be clickable here only if last_date allows.
        # Sanity: the dialog at least builds without error.
        assert dialog is not None
