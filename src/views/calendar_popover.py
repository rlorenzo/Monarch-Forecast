"""Minimal calendar popover for picking a date.

Replaces the stock ``ft.DatePicker`` dialog in places where the Material
header (showing the selected date on the left) and the explicit OK button
are friction rather than help. The popover renders just the month grid
and auto-saves the picked day — tap a date and the dialog closes,
invoking the ``on_pick`` callback.
"""

from __future__ import annotations

import calendar
from collections.abc import Callable
from datetime import date

import flet as ft

_WEEKDAY_LABELS = ("S", "M", "T", "W", "T", "F", "S")


def show_calendar_popover(
    page: ft.Page | ft.BasePage,
    initial_date: date,
    on_pick: Callable[[date], None],
    *,
    first_date: date | None = None,
    last_date: date | None = None,
) -> None:
    """Open a calendar popover that auto-saves on tap.

    Args:
        page: The Flet page used for show/pop.
        initial_date: The month to display first, and the pre-highlighted day.
        on_pick: Called with the chosen date when the user taps a day cell.
        first_date: Earliest selectable date (inclusive). Days before this
            are disabled. Defaults to no lower bound.
        last_date: Latest selectable date (inclusive). Days after this are
            disabled. Defaults to no upper bound.
    """
    # Mutable cursor so prev/next month buttons can update the visible grid.
    cursor = {"year": initial_date.year, "month": initial_date.month}

    month_label = ft.Text("", size=15, weight=ft.FontWeight.W_600)
    grid_container = ft.Container()

    def in_range(d: date) -> bool:
        if first_date is not None and d < first_date:
            return False
        return not (last_date is not None and d > last_date)

    def handle_pick(picked: date) -> None:
        page.pop_dialog()
        on_pick(picked)

    def make_day_cell(d: date | None) -> ft.Control:
        """Build a single 36x36 cell — a day button, today highlight, or blank."""
        if d is None:
            return ft.Container(width=36, height=36)
        is_today = d == date.today()
        is_selected = d == initial_date
        enabled = in_range(d)
        bg = None
        fg = None
        if is_selected:
            bg = ft.Colors.PRIMARY
            fg = ft.Colors.ON_PRIMARY
        elif is_today:
            bg = ft.Colors.PRIMARY_CONTAINER
            fg = ft.Colors.ON_PRIMARY_CONTAINER
        return ft.Container(
            content=ft.Text(
                str(d.day),
                size=13,
                color=fg if fg is not None else ft.Colors.ON_SURFACE,
                text_align=ft.TextAlign.CENTER,
                weight=ft.FontWeight.W_600 if (is_today or is_selected) else None,
            ),
            width=36,
            height=36,
            alignment=ft.Alignment(0, 0),
            bgcolor=bg,
            border_radius=18,
            ink=enabled,
            on_click=(lambda _e, _d=d: handle_pick(_d)) if enabled else None,
            tooltip=d.strftime("%A, %b %d, %Y") if enabled else None,
            opacity=1.0 if enabled else 0.35,
        )

    def build_month_grid() -> ft.Column:
        y, m = cursor["year"], cursor["month"]
        month_label.value = date(y, m, 1).strftime("%B %Y")

        # calendar.Calendar(firstweekday=6) starts the week on Sunday, so
        # we get rows of [S, M, T, W, T, F, S] — matching _WEEKDAY_LABELS.
        cal = calendar.Calendar(firstweekday=6)
        weeks: list[list[ft.Control]] = []
        for week in cal.monthdayscalendar(y, m):
            row_cells: list[ft.Control] = []
            for day_num in week:
                if day_num == 0:
                    row_cells.append(make_day_cell(None))
                else:
                    row_cells.append(make_day_cell(date(y, m, day_num)))
            weeks.append(row_cells)

        header_row = ft.Row(
            [ft.Text(w, size=11, color=ft.Colors.ON_SURFACE_VARIANT) for w in _WEEKDAY_LABELS],
            spacing=0,
            alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            width=36 * 7,
        )

        grid_rows = [
            ft.Row(row, spacing=0, alignment=ft.MainAxisAlignment.SPACE_BETWEEN, width=36 * 7)
            for row in weeks
        ]

        return ft.Column(
            [header_row, *grid_rows],
            spacing=4,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        )

    def shift_month(delta: int) -> None:
        y, m = cursor["year"], cursor["month"]
        m += delta
        while m < 1:
            m += 12
            y -= 1
        while m > 12:
            m -= 12
            y += 1
        cursor["year"] = y
        cursor["month"] = m
        grid_container.content = build_month_grid()
        try:
            grid_container.update()
            month_label.update()
        except RuntimeError:
            pass

    prev_button = ft.Semantics(
        button=True,
        label="Previous month",
        content=ft.IconButton(
            icon=ft.Icons.CHEVRON_LEFT,
            tooltip="Previous month",
            on_click=lambda _e: shift_month(-1),
        ),
    )
    next_button = ft.Semantics(
        button=True,
        label="Next month",
        content=ft.IconButton(
            icon=ft.Icons.CHEVRON_RIGHT,
            tooltip="Next month",
            on_click=lambda _e: shift_month(1),
        ),
    )

    grid_container.content = build_month_grid()

    dialog = ft.AlertDialog(
        content=ft.Column(
            [
                ft.Row(
                    [prev_button, month_label, next_button],
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    width=36 * 7,
                ),
                grid_container,
            ],
            spacing=8,
            tight=True,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        content_padding=ft.Padding.all(12),
        inset_padding=ft.Padding.all(24),
    )
    page.show_dialog(dialog)
