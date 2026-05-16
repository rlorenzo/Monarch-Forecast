"""Editorial adjustments panel: one-off transactions + recurring overrides.

Replaces the previous stock Material 3 chrome (``ft.Card``,
``ft.ExpansionTile``, ``Red_400``/``Green_400`` accents) with the
paper-and-ink system used on Overview and Transactions. Two sections
stacked vertically with a hairline separator:

1. **One-off transactions** — inline form (description, amount, type,
   date) plus a mini-ledger of existing entries: eyebrow date in the
   left gutter, Inter 600 description, signed amount in signal color
   with true-minus (U+2212), and per-row pencil + remove pencils.
2. **Recurring** — checkbox-toggleable rows with signal arrows,
   frequency pill, next-occurrence date, current amount, and an
   inline override field with a reset affordance when overridden.

The panel exposes ``oneoff_section`` and ``recurring_section`` as
attributes so the dashboard could slot a third section (credit cards)
between them; today it stacks both back-to-back with a hairline rule.

Public API (consumed by dashboard.py) is unchanged: ``adjusted_recurring_items``,
``one_off_transactions``, ``update_recurring_items``, ``refresh_override_display``,
``find_one_off_index``, ``update_one_off``, ``add_one_off``.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import replace
from datetime import date, datetime, timedelta
from typing import Any

import flet as ft

from src.data.models import ForecastTransaction, RecurringItem
from src.data.preferences import Preferences
from src.views import tokens
from src.views.calendar_popover import show_calendar_popover

# Formats accepted when a user types a date into the one-off date TextField.
# Keep the canonical ISO form first so round-trips are stable.
_DATE_INPUT_FORMATS = (
    "%Y-%m-%d",  # canonical ISO form — what the field normally displays
    "%b %d, %Y",  # legacy display format ("Jan 05, 2026")
    "%m/%d/%Y",
    "%m-%d-%Y",
)


def _parse_date_input(raw: str) -> date | None:
    """Parse a user-typed date string, accepting several common formats.

    Returns None if the input can't be parsed. Used by the one-off date
    TextFields so keyboard users can type a date directly instead of
    being forced through the calendar popover.
    """
    text = (raw or "").strip()
    if not text:
        return None
    for fmt in _DATE_INPUT_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _schedule_focus(page: ft.Page | ft.BasePage, control: ft.Control) -> None:
    """Schedule ``control.focus()`` from a synchronous handler.

    Flet 0.84 made ``Control.focus()`` an async coroutine. Calling it
    directly from a sync handler produces a RuntimeWarning and the focus
    silently no-ops. This routes the coroutine through ``page.run_task``
    so it actually runs; the headless ``BasePage`` is accepted but a
    no-op (no event loop attached).
    """
    focus_fn = getattr(control, "focus", None)
    if focus_fn is None:
        return

    async def _do() -> None:
        try:
            await focus_fn()
        except (AssertionError, RuntimeError):
            pass

    if not isinstance(page, ft.Page):
        return
    try:
        page.run_task(_do)
    except (AssertionError, RuntimeError):
        pass


# ---------------------------------------------------------------------------
# Editorial primitives
# ---------------------------------------------------------------------------
#
# Small composable bits shared across the panel sections + dialogs. None
# of these touch state; they're presentation only. Kept at module scope
# (not class) so dashboard.py can borrow them when it needs the same
# look for the credit-card section, which lives outside this panel.


def _eyebrow(text: str, color: str = tokens.INK_3) -> ft.Text:
    """11pt UPPERCASE Label-role eyebrow."""
    return ft.Text(text.upper(), style=tokens.label_style(color))


def _section_header(
    eyebrow_text: str,
    title: str,
    subtitle: str,
    meta: ft.Control | None = None,
    *,
    trailing: ft.Control | None = None,
    on_click: Callable[[ft.Event[ft.Container]], Any] | None = None,
) -> ft.Control:
    """Editorial section header: eyebrow + Fraunces headline + Inter subtitle.

    ``meta`` (optional) renders as a small pill placed inline just after
    the headline. Earlier attempts to push the chip to the right edge
    with ``Row(Container(expand=True))`` silently collapsed the whole
    row to zero height inside a tight Column parent — keep this layout
    flat to avoid resurrecting that bug.

    ``trailing`` (optional) is rendered at the right of the title row —
    typically a chevron icon when the section is collapsible.

    ``on_click`` (optional) makes the whole header a clickable surface.
    Used by sections that toggle their body via the section header
    (currently: Credit Cards, which is collapsed by default).
    """
    headline = ft.Text(title, style=tokens.headline_style(tokens.INK))
    row_children: list[ft.Control] = [headline]
    if meta is not None:
        row_children.append(meta)
    if trailing is not None:
        row_children.append(trailing)
    title_row: ft.Control = (
        ft.Row(
            controls=row_children,
            spacing=12,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
            tight=True,
        )
        if len(row_children) > 1
        else headline
    )

    column = ft.Column(
        controls=[
            _eyebrow(eyebrow_text),
            ft.Container(height=4),
            title_row,
            ft.Text(subtitle, style=tokens.body_style(tokens.INK_2)),
        ],
        spacing=2,
        tight=True,
    )

    if on_click is None:
        return column

    # Clickable variant — wrap in a Container with a subtle PAPER_2 hover
    # tint so the user knows the whole header is a hit target.
    def _on_hover(e: ft.Event[ft.Container]) -> None:
        is_in = e.data == "true"
        e.control.bgcolor = tokens.PAPER_2 if is_in else "transparent"
        try:
            e.control.update()
        except (RuntimeError, AssertionError):
            pass

    return ft.Container(
        content=column,
        on_click=on_click,
        on_hover=_on_hover,
        bgcolor="transparent",
        padding=ft.Padding.symmetric(horizontal=4, vertical=4),
        border_radius=ft.BorderRadius.all(6),
        tooltip="Click to expand or collapse",
    )


def _section_rule() -> ft.Control:
    """Hairline divider between editorial sections."""
    return ft.Container(
        height=1,
        bgcolor=tokens.RULE,
        margin=ft.Margin.symmetric(vertical=32),
    )


def _meta_chip(text: str) -> ft.Control:
    """Small pill displaying a counted status (e.g. "3 of 12 included").

    Stays PAPER_2 / INK_2 unconditionally — this isn't a signal; it's a
    quiet status badge.
    """
    return ft.Container(
        content=ft.Text(
            text,
            style=ft.TextStyle(
                font_family=tokens.FONT_BODY,
                size=11,
                weight=ft.FontWeight.W_600,
                color=tokens.INK_2,
                letter_spacing=0.4,
                height=1.2,
            ),
        ),
        bgcolor=tokens.PAPER_2,
        padding=ft.Padding.symmetric(horizontal=10, vertical=4),
        border_radius=ft.BorderRadius.all(999),
        border=ft.Border.all(1, tokens.RULE),
    )


def _frequency_chip(label: str) -> ft.Control:
    """Pill used as a tag on a recurring row (monthly, biweekly, etc.).

    Always quiet: PAPER_2 fill, INK_2 text, no border. Matches DESIGN.md
    ``chip-recurring`` token: not a signal, just a small typographic
    badge — kept distinct from the filter chips on the Transactions tab
    which are interactive.
    """
    return ft.Container(
        content=ft.Text(
            label.upper(),
            style=ft.TextStyle(
                font_family=tokens.FONT_BODY,
                size=10,
                weight=ft.FontWeight.W_600,
                color=tokens.INK_2,
                letter_spacing=0.6,
                height=1.2,
            ),
        ),
        bgcolor=tokens.PAPER_2,
        padding=ft.Padding.symmetric(horizontal=8, vertical=3),
        border_radius=ft.BorderRadius.all(3),
    )


def _ledger_field(
    *,
    label: str | None = None,
    value: str = "",
    width: int | None = None,
    hint: str | None = None,
    prefix: ft.Control | None = None,
    keyboard_type: ft.KeyboardType | None = None,
    autofocus: bool = False,
    on_submit: Callable[[ft.Event[ft.TextField]], Any] | None = None,
    on_blur: Callable[[ft.Event[ft.TextField]], Any] | None = None,
    on_change: Callable[[ft.Event[ft.TextField]], Any] | None = None,
    tooltip: str | None = None,
    dense: bool = False,
    border_color: str | None = None,
    border_width: int | None = None,
) -> ft.TextField:
    """A TextField with paper-and-ink styling.

    PAPER fill, RULE hairline at rest, CORAL 2px focus ring, INK_3 hint.
    Pulled out as a helper because every adjustment input wants the
    same chrome — keeping them visually identical is critical for the
    section's rhythm.
    """
    # Flet's TextField types ``keyboard_type`` as non-Optional; default to
    # TEXT when the caller doesn't provide one.
    kt = keyboard_type if keyboard_type is not None else ft.KeyboardType.TEXT
    return ft.TextField(
        label=label,
        value=value,
        width=width,
        hint_text=hint,
        prefix=prefix,
        keyboard_type=kt,
        autofocus=autofocus,
        on_submit=on_submit,
        on_blur=on_blur,
        on_change=on_change,
        tooltip=tooltip,
        dense=dense,
        bgcolor=tokens.PAPER,
        color=tokens.INK,
        text_size=13,
        border_color=border_color if border_color is not None else tokens.RULE,
        focused_border_color=tokens.CORAL,
        border_width=border_width if border_width is not None else 1,
        focused_border_width=2,
        label_style=ft.TextStyle(
            font_family=tokens.FONT_BODY,
            size=11,
            weight=ft.FontWeight.W_500,
            color=tokens.INK_2,
            letter_spacing=0.4,
        ),
        hint_style=ft.TextStyle(
            font_family=tokens.FONT_BODY,
            size=13,
            color=tokens.INK_3,
        ),
        content_padding=ft.Padding.symmetric(horizontal=12, vertical=10),
    )


def _ledger_dropdown(
    *,
    label: str,
    value: str,
    options: list[tuple[str, str]],
    width: int | None = None,
    tooltip: str | None = None,
) -> ft.Dropdown:
    """Paper-and-ink styled Dropdown matching ``_ledger_field`` chrome."""
    return ft.Dropdown(
        label=label,
        value=value,
        width=width,
        tooltip=tooltip,
        options=[ft.dropdown.Option(key, text) for key, text in options],
        bgcolor=tokens.PAPER,
        color=tokens.INK,
        text_size=13,
        border_color=tokens.RULE,
        focused_border_color=tokens.CORAL,
        border_width=1,
        focused_border_width=2,
        label_style=ft.TextStyle(
            font_family=tokens.FONT_BODY,
            size=11,
            weight=ft.FontWeight.W_500,
            color=tokens.INK_2,
            letter_spacing=0.4,
        ),
        content_padding=ft.Padding.symmetric(horizontal=12, vertical=10),
    )


def coral_button(
    label: str,
    *,
    icon: ft.IconData | None = None,
    on_click: Callable[[ft.Event[ft.Container]], Any],
    tooltip: str | None = None,
    sr_label: str | None = None,
) -> ft.Control:
    """Coral primary CTA — paper text, 6px radius, Container-based.

    Built from a Container so Material's tonal-elevation chrome doesn't
    swallow the explicit bgcolor (which it does on ``ft.FilledButton``).
    Wrapped in Semantics so screen readers announce a button with the
    given accessible name.
    """
    text = ft.Text(
        label,
        style=ft.TextStyle(
            font_family=tokens.FONT_BODY,
            size=14,
            weight=ft.FontWeight.W_600,
            color=tokens.PAPER,
            height=1.2,
        ),
    )
    body: ft.Control
    if icon is not None:
        body = ft.Row(
            controls=[ft.Icon(icon, size=18, color=tokens.PAPER), text],
            spacing=8,
            tight=True,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )
    else:
        body = text

    def _on_hover(e: ft.Event[ft.Container]) -> None:
        is_in = e.data == "true"
        e.control.bgcolor = tokens.CORAL_DEEP if is_in else tokens.CORAL
        try:
            e.control.update()
        except (RuntimeError, AssertionError):
            pass

    button = ft.Container(
        content=body,
        bgcolor=tokens.CORAL,
        padding=ft.Padding.symmetric(horizontal=16, vertical=10),
        border_radius=ft.BorderRadius.all(6),
        on_click=on_click,
        on_hover=_on_hover,
        tooltip=tooltip or label,
        animate_scale=ft.Animation(150, ft.AnimationCurve.EASE_OUT_QUART),
    )
    return ft.Semantics(button=True, label=sr_label or tooltip or label, content=button)


def ghost_button(
    label: str,
    *,
    on_click: Callable[[ft.Event[ft.Container]], Any],
    tooltip: str | None = None,
) -> ft.Control:
    """Quiet text button — transparent fill, INK_2 text, PAPER_2 hover."""
    text = ft.Text(
        label,
        style=ft.TextStyle(
            font_family=tokens.FONT_BODY,
            size=14,
            weight=ft.FontWeight.W_600,
            color=tokens.INK_2,
            height=1.2,
        ),
    )

    def _on_hover(e: ft.Event[ft.Container]) -> None:
        is_in = e.data == "true"
        e.control.bgcolor = tokens.PAPER_2 if is_in else "transparent"
        try:
            e.control.update()
        except (RuntimeError, AssertionError):
            pass

    button = ft.Container(
        content=text,
        bgcolor="transparent",
        padding=ft.Padding.symmetric(horizontal=14, vertical=10),
        border_radius=ft.BorderRadius.all(6),
        on_click=on_click,
        on_hover=_on_hover,
        tooltip=tooltip or label,
    )
    return ft.Semantics(button=True, label=label, content=button)


def ink_button(
    label: str,
    *,
    on_click: Callable[[ft.Event[ft.Container]], Any],
    tooltip: str | None = None,
) -> ft.Control:
    """Ink-on-paper button used for dialog confirm/dismiss actions.

    INK fill at rest, INK_2 on hover. ~13:1 contrast on PAPER text — well
    above WCAG AA's 4.5:1. Used as the dialog "Cancel" partner to the
    coral "Save" so the action axis stays calm without lapsing into
    Material's TextButton chrome.
    """
    text = ft.Text(
        label,
        style=ft.TextStyle(
            font_family=tokens.FONT_BODY,
            size=14,
            weight=ft.FontWeight.W_600,
            color=tokens.PAPER,
            height=1.2,
        ),
    )

    def _on_hover(e: ft.Event[ft.Container]) -> None:
        is_in = e.data == "true"
        e.control.bgcolor = tokens.INK_2 if is_in else tokens.INK
        try:
            e.control.update()
        except (RuntimeError, AssertionError):
            pass

    button = ft.Container(
        content=text,
        bgcolor=tokens.INK,
        padding=ft.Padding.symmetric(horizontal=18, vertical=10),
        border_radius=ft.BorderRadius.all(6),
        on_click=on_click,
        on_hover=_on_hover,
        tooltip=tooltip or label,
    )
    return ft.Semantics(button=True, label=label, content=button)


def _calendar_icon_button(
    on_click: Callable[[ft.Event[ft.IconButton]], Any],
    *,
    sr_label: str = "Open calendar to pick date",
) -> ft.Control:
    """The keyboard-accessible calendar affordance next to a date field."""
    return ft.Semantics(
        button=True,
        label=sr_label,
        content=ft.IconButton(
            icon=ft.Icons.CALENDAR_MONTH,
            icon_color=tokens.INK_2,
            tooltip="Pick date from calendar",
            on_click=on_click,
        ),
    )


def _dialog_error_text() -> ft.Text:
    """Empty error Text styled in signal-negative; updated in place."""
    return ft.Text(
        "",
        style=ft.TextStyle(
            font_family=tokens.FONT_BODY,
            size=12,
            color=tokens.SIGNAL_NEGATIVE,
            height=1.3,
        ),
    )


# ---------------------------------------------------------------------------
# Dialogs
# ---------------------------------------------------------------------------


def _dialog_title(text: str) -> ft.Control:
    """Fraunces 24pt headline used as an AlertDialog title."""
    return ft.Text(text, style=tokens.headline_style(tokens.INK))


def _dialog_subtitle(text: str) -> ft.Control:
    """Inter 13pt INK_2 secondary line under a dialog title."""
    return ft.Text(text, style=tokens.body_style(tokens.INK_2))


def show_amount_edit_dialog(
    page: ft.Page | ft.BasePage,
    title: str,
    subtitle: str,
    current_amount: float,
    on_save: Callable[[float], None],
    on_reset: Callable[[], None] | None = None,
) -> None:
    """Open the editorial dollar-amount edit dialog.

    Args:
        page: Flet page used for show/pop.
        title: Headline (e.g. "Edit Chase Sapphire payment").
        subtitle: Secondary line (e.g. the transaction date).
        current_amount: Pre-filled positive amount.
        on_save: Called with the new positive amount when the user saves.
        on_reset: Optional callback. When provided, a Reset action appears.
    """
    amount_field = _ledger_field(
        label="AMOUNT",
        prefix=ft.Text(
            "$",
            style=ft.TextStyle(
                font_family=tokens.FONT_BODY,
                size=13,
                color=tokens.INK_2,
            ),
        ),
        value=f"{current_amount:.2f}",
        keyboard_type=ft.KeyboardType.NUMBER,
        autofocus=True,
        width=200,
    )
    error_text = _dialog_error_text()

    def handle_save(_: ft.Event[ft.Container]) -> None:
        raw = (amount_field.value or "").replace(",", "").replace("$", "").strip()
        try:
            value = float(raw)
        except ValueError:
            error_text.value = "Enter a valid number."
            error_text.update()
            _schedule_focus(page, amount_field)
            return
        if value <= 0:
            error_text.value = "Amount must be greater than 0."
            error_text.update()
            _schedule_focus(page, amount_field)
            return
        page.pop_dialog()
        on_save(value)

    def handle_reset(_: ft.Event[ft.Container]) -> None:
        page.pop_dialog()
        if on_reset is not None:
            on_reset()

    def handle_cancel(_: ft.Event[ft.Container]) -> None:
        page.pop_dialog()

    actions: list[ft.Control] = [ghost_button("Cancel", on_click=handle_cancel)]
    if on_reset is not None:
        actions.append(ghost_button("Reset to original", on_click=handle_reset))
    actions.append(coral_button("Save", on_click=handle_save))

    dialog = ft.AlertDialog(
        bgcolor=tokens.PAPER,
        title=_dialog_title(title),
        content=ft.Column(
            [
                _dialog_subtitle(subtitle),
                ft.Container(height=12),
                amount_field,
                ft.Semantics(
                    live_region=True,
                    content=ft.Container(content=error_text, height=18),
                ),
            ],
            spacing=4,
            tight=True,
        ),
        actions=actions,
    )
    page.show_dialog(dialog)


def show_add_one_off_dialog(
    page: ft.Page | ft.BasePage,
    on_save: Callable[[str, float, date, bool], None],
) -> None:
    """Open the editorial dialog to create a new one-off transaction.

    ``on_save`` receives ``(name, positive_amount, date, is_expense)``.
    """
    name_field = _ledger_field(
        label="DESCRIPTION",
        width=280,
        autofocus=True,
        hint="Car repair, tax refund...",
    )
    amount_field = _ledger_field(
        label="AMOUNT",
        prefix=ft.Text(
            "$",
            style=ft.TextStyle(font_family=tokens.FONT_BODY, size=13, color=tokens.INK_2),
        ),
        keyboard_type=ft.KeyboardType.NUMBER,
        width=160,
    )
    type_dropdown = _ledger_dropdown(
        label="TYPE",
        width=140,
        value="expense",
        options=[("expense", "Expense"), ("income", "Income")],
    )
    default_date = date.today() + timedelta(days=7)
    picked_date: list[date] = [default_date]
    date_display = _ledger_field(
        label="DATE",
        width=160,
        value=default_date.strftime("%Y-%m-%d"),
        hint="YYYY-MM-DD",
        tooltip="Type a date or click the calendar button",
    )

    def on_date_typed(_: ft.Event[ft.TextField]) -> None:
        parsed = _parse_date_input(date_display.value or "")
        if parsed is not None:
            picked_date[0] = parsed
            date_display.value = parsed.strftime("%Y-%m-%d")
            date_display.update()

    date_display.on_submit = on_date_typed
    date_display.on_blur = on_date_typed

    def on_calendar_pick(d: date) -> None:
        picked_date[0] = d
        date_display.value = d.strftime("%Y-%m-%d")
        date_display.update()

    def open_calendar(_: ft.Event[ft.IconButton]) -> None:
        current = _parse_date_input(date_display.value or "") or picked_date[0]
        show_calendar_popover(
            page,
            initial_date=current,
            on_pick=on_calendar_pick,
            first_date=date.today(),
            last_date=date.today() + timedelta(days=365),
        )

    calendar_button = _calendar_icon_button(open_calendar)
    error_text = _dialog_error_text()

    def handle_save(_: ft.Event[ft.Container]) -> None:
        new_name = (name_field.value or "").strip()
        if not new_name:
            error_text.value = "Description is required."
            error_text.update()
            _schedule_focus(page, name_field)
            return
        raw = (amount_field.value or "").replace(",", "").replace("$", "").strip()
        try:
            value = float(raw)
        except ValueError:
            error_text.value = "Enter a valid number."
            error_text.update()
            _schedule_focus(page, amount_field)
            return
        if value <= 0:
            error_text.value = "Amount must be greater than 0."
            error_text.update()
            _schedule_focus(page, amount_field)
            return
        typed_date = _parse_date_input(date_display.value or "")
        if typed_date is None:
            error_text.value = "Enter a valid date (YYYY-MM-DD)."
            error_text.update()
            _schedule_focus(page, date_display)
            return
        picked_date[0] = typed_date
        is_expense = type_dropdown.value == "expense"
        page.pop_dialog()
        on_save(new_name, value, picked_date[0], is_expense)

    def handle_cancel(_: ft.Event[ft.Container]) -> None:
        page.pop_dialog()

    dialog = ft.AlertDialog(
        bgcolor=tokens.PAPER,
        title=_dialog_title("Add a one-off"),
        content=ft.Column(
            [
                _dialog_subtitle(
                    "A future expense or income that isn't recurring."
                    " It will appear on the chart and in Transactions."
                ),
                ft.Container(height=12),
                name_field,
                ft.Row(
                    [amount_field, type_dropdown],
                    spacing=12,
                    vertical_alignment=ft.CrossAxisAlignment.START,
                ),
                ft.Row(
                    [date_display, calendar_button],
                    spacing=8,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                ft.Semantics(
                    live_region=True,
                    content=ft.Container(content=error_text, height=18),
                ),
            ],
            spacing=10,
            tight=True,
        ),
        actions=[
            ghost_button("Cancel", on_click=handle_cancel),
            coral_button("Add transaction", on_click=handle_save),
        ],
    )
    page.show_dialog(dialog)


def show_edit_one_off_dialog(
    page: ft.Page | ft.BasePage,
    existing: ForecastTransaction,
    on_save: Callable[[str, float, date], None],
) -> None:
    """Open the editorial dialog to edit an existing one-off.

    The sign (income vs expense) is preserved from ``existing``.
    ``on_save`` receives ``(new_name, new_positive_amount, new_date)``.
    """
    name_field = _ledger_field(
        label="DESCRIPTION",
        value=existing.name,
        width=280,
        autofocus=True,
    )
    amount_field = _ledger_field(
        label="AMOUNT",
        prefix=ft.Text(
            "$",
            style=ft.TextStyle(font_family=tokens.FONT_BODY, size=13, color=tokens.INK_2),
        ),
        value=f"{abs(existing.amount):.2f}",
        keyboard_type=ft.KeyboardType.NUMBER,
        width=200,
    )

    picked_date: list[date] = [existing.date]
    date_display = _ledger_field(
        label="DATE",
        width=160,
        value=existing.date.strftime("%Y-%m-%d"),
        hint="YYYY-MM-DD",
        tooltip="Type a date or click the calendar button",
    )

    def on_date_typed(_: ft.Event[ft.TextField]) -> None:
        parsed = _parse_date_input(date_display.value or "")
        if parsed is not None:
            picked_date[0] = parsed
            date_display.value = parsed.strftime("%Y-%m-%d")
            date_display.update()

    date_display.on_submit = on_date_typed
    date_display.on_blur = on_date_typed

    def on_calendar_pick(d: date) -> None:
        picked_date[0] = d
        date_display.value = d.strftime("%Y-%m-%d")
        date_display.update()

    def open_calendar(_: ft.Event[ft.IconButton]) -> None:
        current = _parse_date_input(date_display.value or "") or picked_date[0]
        show_calendar_popover(
            page,
            initial_date=current,
            on_pick=on_calendar_pick,
            first_date=date.today(),
            last_date=date.today() + timedelta(days=365),
        )

    calendar_button = _calendar_icon_button(open_calendar)
    error_text = _dialog_error_text()

    def handle_save(_: ft.Event[ft.Container]) -> None:
        new_name = (name_field.value or "").strip()
        if not new_name:
            error_text.value = "Description is required."
            error_text.update()
            _schedule_focus(page, name_field)
            return
        raw = (amount_field.value or "").replace(",", "").replace("$", "").strip()
        try:
            value = float(raw)
        except ValueError:
            error_text.value = "Enter a valid number."
            error_text.update()
            _schedule_focus(page, amount_field)
            return
        if value <= 0:
            error_text.value = "Amount must be greater than 0."
            error_text.update()
            _schedule_focus(page, amount_field)
            return
        typed_date = _parse_date_input(date_display.value or "")
        if typed_date is None:
            error_text.value = "Enter a valid date (YYYY-MM-DD)."
            error_text.update()
            _schedule_focus(page, date_display)
            return
        picked_date[0] = typed_date
        page.pop_dialog()
        on_save(new_name, value, picked_date[0])

    def handle_cancel(_: ft.Event[ft.Container]) -> None:
        page.pop_dialog()

    dialog = ft.AlertDialog(
        bgcolor=tokens.PAPER,
        title=_dialog_title("Edit one-off"),
        content=ft.Column(
            [
                _dialog_subtitle(existing.date.strftime("%b %d, %Y")),
                ft.Container(height=12),
                name_field,
                amount_field,
                ft.Row(
                    [date_display, calendar_button],
                    spacing=8,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                ft.Semantics(
                    live_region=True,
                    content=ft.Container(content=error_text, height=18),
                ),
            ],
            spacing=10,
            tight=True,
        ),
        actions=[
            ghost_button("Cancel", on_click=handle_cancel),
            coral_button("Save", on_click=handle_save),
        ],
    )
    page.show_dialog(dialog)


# ---------------------------------------------------------------------------
# AdjustmentsPanel
# ---------------------------------------------------------------------------


# Column widths for the one-off mini-ledger (gutter + body row). Locked
# integers so the eyebrow date / description / amount columns align
# vertically across rows. Matches the rhythm of the Transactions tab
# day-block ledger but simpler (no day grouping — every one-off is a
# user-chosen single occurrence).
_OFF_DATE_W = 78
_OFF_NAME_W = 240
_OFF_AMOUNT_W = 120

# Column widths for the recurring rows.
_RC_CHECK_W = 28
_RC_ARROW_W = 18
_RC_NAME_W = 200
_RC_FREQ_W = 84
_RC_NEXT_W = 88
_RC_AMOUNT_W = 96
_RC_OVERRIDE_W = 92


def _column_label(text: str, width: int, *, align_right: bool = False) -> ft.Control:
    """Mini-ledger column header, same vocabulary as Transactions."""
    label = ft.Text(
        text.upper(),
        style=ft.TextStyle(
            font_family=tokens.FONT_BODY,
            size=11,
            weight=ft.FontWeight.W_600,
            color=tokens.INK_3,
            letter_spacing=0.66,
            height=1.2,
        ),
    )
    return ft.Container(
        content=label,
        width=width,
        alignment=ft.Alignment(1, 0) if align_right else ft.Alignment(-1, 0),
    )


def _signed_glyph(amount: float) -> str:
    """True minus (U+2212) for negatives, plus for positives.

    Avoids the hyphen-minus which renders narrower than the plus and
    unbalances the column. Matches the Transactions ledger.
    """
    return "−" if amount < 0 else "+"


class AdjustmentsPanel(ft.Column):
    """Editorial panel for one-off + recurring forecast adjustments.

    Replaces the previous ``ft.Card`` + ``ft.ExpansionTile`` chrome with
    typographic sections built from primitives. Public API is unchanged
    so dashboard.py drives this exactly as before.
    """

    def __init__(
        self,
        recurring_items: list[RecurringItem],
        on_change: Callable[[], None],
        preferences: Preferences | None = None,
    ) -> None:
        super().__init__()
        self._recurring_items = recurring_items
        self._on_change = on_change
        self._prefs = preferences or Preferences()
        self._selected_account_id = ""
        self._one_offs: list[ForecastTransaction] = self._prefs.one_off_transactions
        # Backfill stable ids for any legacy entries persisted before ids existed.
        if any(not t.id for t in self._one_offs):
            self._one_offs = [replace(t, id=t.id or uuid.uuid4().hex) for t in self._one_offs]
            self._prefs.set_one_off_transactions(self._one_offs)

        self.spacing = 0

        # --- One-off form fields ----------------------------------------
        # ``_oneoff_name`` is read by the dashboard when ⌘3 switches to
        # the Adjustments tab — keep the attribute name stable.
        self._oneoff_name = _ledger_field(
            label="DESCRIPTION",
            width=240,
            hint="Car repair, tax refund...",
        )
        self._oneoff_amount = _ledger_field(
            label="AMOUNT",
            prefix=ft.Text(
                "$",
                style=ft.TextStyle(
                    font_family=tokens.FONT_BODY,
                    size=13,
                    color=tokens.INK_2,
                ),
            ),
            width=140,
            keyboard_type=ft.KeyboardType.NUMBER,
        )
        default_date = date.today() + timedelta(days=7)
        self._oneoff_picked_date: date = default_date
        self._oneoff_date_display = _ledger_field(
            label="DATE",
            width=148,
            value=default_date.strftime("%Y-%m-%d"),
            hint="YYYY-MM-DD",
            tooltip="Type a date or click the calendar button",
            on_submit=self._on_oneoff_date_typed,
            on_blur=self._on_oneoff_date_typed,
        )
        self._oneoff_calendar_button = _calendar_icon_button(self._open_oneoff_calendar)
        self._oneoff_type = _ledger_dropdown(
            label="TYPE",
            width=128,
            value="expense",
            options=[("expense", "Expense"), ("income", "Income")],
        )
        self._oneoff_error = _dialog_error_text()
        self._oneoff_list = ft.Column(spacing=0)
        self._oneoff_empty_state = ft.Container(
            content=ft.Text(
                "No one-offs yet. Add a future expense or income above to model it.",
                style=ft.TextStyle(
                    font_family=tokens.FONT_BODY,
                    size=12,
                    color=tokens.INK_3,
                    italic=True,
                    height=1.4,
                ),
            ),
            padding=ft.Padding.symmetric(vertical=12),
        )

        # --- Recurring section ------------------------------------------
        self._override_list = ft.Column(spacing=0)
        # Construct the meta chip with a held reference to the inner Text so
        # ``_rebuild_override_rows`` can update the count without traversing
        # the chip's ``content`` (which ty can't narrow through the union).
        self._recurring_meta_text = ft.Text(
            "0 of 0 included",
            style=ft.TextStyle(
                font_family=tokens.FONT_BODY,
                size=11,
                weight=ft.FontWeight.W_600,
                color=tokens.INK_2,
                letter_spacing=0.4,
                height=1.2,
            ),
        )
        self._recurring_meta_chip = ft.Container(
            content=self._recurring_meta_text,
            bgcolor=tokens.PAPER_2,
            padding=ft.Padding.symmetric(horizontal=10, vertical=4),
            border_radius=ft.BorderRadius.all(999),
            border=ft.Border.all(1, tokens.RULE),
        )
        self._recurring_other_account_note = ft.Container()

        # --- Section builders -------------------------------------------
        self.oneoff_section = self._build_oneoff_section()
        self.recurring_section = self._build_recurring_section()

        self.controls = [
            self.oneoff_section,
            _section_rule(),
            self.recurring_section,
        ]

    # ------------------------------------------------------------------
    # Section builders
    # ------------------------------------------------------------------

    def _build_oneoff_section(self) -> ft.Control:
        """The "Add a one-off transaction" section.

        Layout:

        - Editorial section header.
        - Inline form (description / amount / type / date / calendar /
          coral Add button), wrapped in a quiet paper-2 container so the
          form area visually separates from the section header without
          stamping a Material card on the page.
        - Mini-ledger header + list of existing one-offs (or empty state).
        """
        form_row = ft.Row(
            controls=[
                self._oneoff_name,
                self._oneoff_amount,
                self._oneoff_type,
                self._oneoff_date_display,
                self._oneoff_calendar_button,
                coral_button(
                    "Add",
                    icon=ft.Icons.ADD,
                    on_click=lambda e: self._add_one_off(e),
                    tooltip="Add this one-off to the forecast",
                    sr_label="Add one-off transaction",
                ),
            ],
            spacing=10,
            wrap=True,
            run_spacing=10,
            vertical_alignment=ft.CrossAxisAlignment.END,
        )

        form_container = ft.Container(
            content=form_row,
            padding=ft.Padding.symmetric(horizontal=16, vertical=14),
            bgcolor=tokens.PAPER_2,
            border=ft.Border.all(1, tokens.RULE),
            border_radius=ft.BorderRadius.all(10),
        )

        ledger_header = ft.Container(
            content=ft.Row(
                controls=[
                    _column_label("Date", _OFF_DATE_W),
                    _column_label("Description", _OFF_NAME_W),
                    _column_label("Amount", _OFF_AMOUNT_W, align_right=True),
                ],
                spacing=0,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=ft.Padding.only(bottom=8, top=4),
            border=ft.Border(bottom=ft.BorderSide(1, tokens.RULE)),
        )

        return ft.Column(
            controls=[
                _section_header(
                    "One-off transactions",
                    "Model unplanned events",
                    "Future expenses or income that aren't recurring.",
                ),
                ft.Container(height=16),
                form_container,
                ft.Semantics(
                    live_region=True,
                    content=ft.Container(content=self._oneoff_error, height=18),
                ),
                ft.Container(height=12),
                ledger_header,
                self._oneoff_list,
                self._oneoff_empty_state,
            ],
            spacing=0,
            tight=True,
        )

    def _build_recurring_section(self) -> ft.Control:
        """The "Recurring transactions" section.

        Layout:

        - Editorial section header with a meta pill ("3 of 12 included").
        - Mini-ledger column header.
        - One row per detected recurring item.
        - "X items from other accounts hidden" note when applicable.
        """
        ledger_header = ft.Container(
            content=ft.Row(
                controls=[
                    ft.Container(width=_RC_CHECK_W + _RC_ARROW_W + 8),
                    _column_label("Name", _RC_NAME_W),
                    _column_label("Frequency", _RC_FREQ_W),
                    _column_label("Next", _RC_NEXT_W),
                    _column_label("Amount", _RC_AMOUNT_W, align_right=True),
                    _column_label("Override", _RC_OVERRIDE_W, align_right=True),
                ],
                spacing=8,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=ft.Padding.only(bottom=8, top=4),
            border=ft.Border(bottom=ft.BorderSide(1, tokens.RULE)),
        )

        return ft.Column(
            controls=[
                _section_header(
                    "Recurring",
                    "Tune detected items",
                    "Uncheck to exclude. Override an amount to change this period only.",
                    meta=self._recurring_meta_chip,
                ),
                ft.Container(height=16),
                ledger_header,
                self._override_list,
                self._recurring_other_account_note,
            ],
            spacing=0,
            tight=True,
        )

    # ------------------------------------------------------------------
    # Lifecycle / public API (preserved verbatim from previous panel)
    # ------------------------------------------------------------------

    def did_mount(self) -> None:
        self._rebuild_override_rows()
        if self._one_offs:
            self._rebuild_oneoff_rows()
        else:
            self._update_oneoff_empty_state(empty=True)

    @property
    def one_off_transactions(self) -> list[ForecastTransaction]:
        return list(self._one_offs)

    def _is_item_included(self, item: RecurringItem) -> bool:
        if item.name in self._prefs.excluded_recurring_names:
            return False
        return not (
            self._selected_account_id
            and item.account_id
            and item.account_id != self._selected_account_id
        )

    @property
    def adjusted_recurring_items(self) -> list[RecurringItem]:
        overrides = self._prefs.amount_overrides
        adjusted = []
        for item in self._recurring_items:
            if not self._is_item_included(item):
                continue
            if item.name in overrides:
                adjusted.append(replace(item, amount=overrides[item.name]))
            else:
                adjusted.append(item)
        return adjusted

    def update_recurring_items(
        self,
        items: list[RecurringItem],
        account_id: str | None = "",
    ) -> None:
        self._recurring_items = items
        self._selected_account_id = account_id or ""
        self._rebuild_override_rows()

    def refresh_override_display(self) -> None:
        """Rebuild recurring rows after an override change made elsewhere."""
        self._rebuild_override_rows()

    # ------------------------------------------------------------------
    # One-off form handlers
    # ------------------------------------------------------------------

    def _on_oneoff_calendar_pick(self, d: date) -> None:
        self._oneoff_picked_date = d
        self._oneoff_date_display.value = d.strftime("%Y-%m-%d")
        self._oneoff_date_display.update()

    def _open_oneoff_calendar(self, _: ft.Event[ft.IconButton]) -> None:
        current = _parse_date_input(self._oneoff_date_display.value or "")
        if current is None:
            current = self._oneoff_picked_date
        show_calendar_popover(
            self.page,
            initial_date=current,
            on_pick=self._on_oneoff_calendar_pick,
            first_date=date.today(),
            last_date=date.today() + timedelta(days=365),
        )

    def _on_oneoff_date_typed(self, _e: ft.Event[ft.TextField]) -> None:
        parsed = _parse_date_input(self._oneoff_date_display.value or "")
        if parsed is not None:
            self._oneoff_picked_date = parsed
            self._oneoff_date_display.value = parsed.strftime("%Y-%m-%d")
            self._oneoff_date_display.update()

    def _add_one_off(self, _e: ft.Event[ft.Container]) -> None:
        name = (self._oneoff_name.value or "").strip()
        amount_str = (self._oneoff_amount.value or "").strip()

        if not name:
            self._oneoff_error.value = "Description is required."
            self._oneoff_error.update()
            _schedule_focus(self.page, self._oneoff_name)
            return
        if not amount_str:
            self._oneoff_error.value = "Amount is required."
            self._oneoff_error.update()
            _schedule_focus(self.page, self._oneoff_amount)
            return

        try:
            cleaned = amount_str.replace(",", "").replace("$", "").strip()
            amount = float(cleaned)
        except ValueError:
            self._oneoff_error.value = "Invalid amount."
            self._oneoff_error.update()
            _schedule_focus(self.page, self._oneoff_amount)
            return
        if amount <= 0:
            self._oneoff_error.value = "Amount must be greater than 0."
            self._oneoff_error.update()
            _schedule_focus(self.page, self._oneoff_amount)
            return

        txn_date = _parse_date_input(self._oneoff_date_display.value or "")
        if txn_date is None:
            txn_date = self._oneoff_picked_date
        if txn_date is None:
            self._oneoff_error.value = "Enter a valid date (YYYY-MM-DD)."
            self._oneoff_error.update()
            _schedule_focus(self.page, self._oneoff_date_display)
            return

        self.add_one_off(
            name=name,
            positive_amount=amount,
            txn_date=txn_date,
            is_expense=self._oneoff_type.value == "expense",
        )

        default_date = date.today() + timedelta(days=7)
        self._oneoff_picked_date = default_date
        self._oneoff_name.value = ""
        self._oneoff_amount.value = ""
        self._oneoff_error.value = ""
        self._oneoff_date_display.value = default_date.strftime("%Y-%m-%d")
        self._oneoff_name.update()
        self._oneoff_amount.update()
        self._oneoff_error.update()
        self._oneoff_date_display.update()

    def _remove_one_off(self, index: int, row: ft.Control | None = None) -> None:
        if not (0 <= index < len(self._one_offs)):
            return
        # Swap in a small spinner where the delete pencil was, so the
        # disappear animation isn't an abrupt vanish.
        if isinstance(row, ft.Row) and row.controls:
            row.controls[-1] = ft.ProgressRing(
                width=14, height=14, stroke_width=2, color=tokens.INK_3
            )
            try:
                row.update()
            except RuntimeError:
                pass
        self._one_offs.pop(index)
        self._prefs.set_one_off_transactions(self._one_offs)
        self._rebuild_oneoff_rows()
        self._on_change()

    def add_one_off(
        self,
        name: str,
        positive_amount: float,
        txn_date: date,
        is_expense: bool,
    ) -> None:
        """Append a new one-off transaction and persist.

        Exposed publicly so callers outside the panel (e.g. the
        Transactions tab's add dialog) can add items through the same
        flow.
        """
        signed = -abs(positive_amount) if is_expense else abs(positive_amount)
        self._one_offs.append(
            ForecastTransaction(
                date=txn_date,
                name=name,
                amount=signed,
                category="Adjustment",
                is_recurring=False,
                id=uuid.uuid4().hex,
            )
        )
        self._prefs.set_one_off_transactions(self._one_offs)
        self._rebuild_oneoff_rows()
        self._on_change()

    def find_one_off_index(self, txn: ForecastTransaction) -> int | None:
        """Find a stored one-off by its stable id."""
        if not txn.id:
            return None
        for i, existing in enumerate(self._one_offs):
            if existing.id == txn.id:
                return i
        return None

    def update_one_off(
        self,
        index: int,
        new_name: str,
        new_abs_amount: float,
        new_date: date,
    ) -> None:
        """Update a stored one-off's name, amount, and date.

        Sign (income vs expense) is preserved from the existing entry.
        """
        if not (0 <= index < len(self._one_offs)):
            return
        existing = self._one_offs[index]
        signed = -abs(new_abs_amount) if existing.amount < 0 else abs(new_abs_amount)
        self._one_offs[index] = replace(
            existing,
            name=new_name,
            amount=signed,
            date=new_date,
        )
        self._prefs.set_one_off_transactions(self._one_offs)
        self._rebuild_oneoff_rows()
        self._on_change()

    def _show_edit_one_off_dialog(self, index: int) -> None:
        if not (0 <= index < len(self._one_offs)):
            return
        existing = self._one_offs[index]

        def save(new_name: str, new_amount: float, new_date: date) -> None:
            self.update_one_off(index, new_name, new_amount, new_date)

        show_edit_one_off_dialog(self.page, existing, save)

    # ------------------------------------------------------------------
    # One-off ledger row rendering
    # ------------------------------------------------------------------

    def _update_oneoff_empty_state(self, *, empty: bool) -> None:
        """Toggle the empty-state placeholder under the one-off ledger.

        Defensive against pre-mount state changes — Flet raises on
        ``update()`` for controls that haven't been added to a page yet.
        """
        self._oneoff_empty_state.visible = empty
        try:
            self._oneoff_empty_state.update()
        except (RuntimeError, AssertionError):
            pass

    def _oneoff_row(self, idx: int, txn: ForecastTransaction) -> ft.Control:
        is_expense = txn.amount < 0
        amount_color = tokens.SIGNAL_NEGATIVE if is_expense else tokens.SIGNAL_POSITIVE

        date_cell = ft.Container(
            content=ft.Text(
                txn.date.strftime("%b %d").upper(),
                style=ft.TextStyle(
                    font_family=tokens.FONT_BODY,
                    size=11,
                    weight=ft.FontWeight.W_600,
                    color=tokens.INK_2,
                    letter_spacing=0.66,
                    height=1.2,
                ),
            ),
            width=_OFF_DATE_W,
            alignment=ft.Alignment(-1, 0),
        )
        name_cell = ft.Container(
            content=ft.Text(
                txn.name,
                style=tokens.body_style(tokens.INK),
                max_lines=1,
                overflow=ft.TextOverflow.ELLIPSIS,
                weight=ft.FontWeight.W_600,
            ),
            width=_OFF_NAME_W,
        )
        amount_cell = ft.Container(
            content=ft.Text(
                f"{_signed_glyph(txn.amount)} ${abs(txn.amount):,.2f}",
                style=ft.TextStyle(
                    font_family=tokens.FONT_BODY,
                    size=13,
                    weight=ft.FontWeight.W_600,
                    color=amount_color,
                    height=1.3,
                ),
                semantics_label=(f"{'minus' if is_expense else 'plus'} ${abs(txn.amount):,.2f}"),
            ),
            width=_OFF_AMOUNT_W,
            alignment=ft.Alignment(1, 0),
        )

        edit_btn = ft.Semantics(
            button=True,
            label=f"Edit one-off {txn.name}",
            content=ft.IconButton(
                icon=ft.Icons.EDIT_OUTLINED,
                icon_size=16,
                icon_color=tokens.INK_3,
                tooltip="Edit one-off",
                on_click=lambda _, i=idx: self._show_edit_one_off_dialog(i),
            ),
        )

        # ``row`` is referenced by ``_remove_one_off`` so it can swap the
        # delete pencil for a small spinner during the remove transition.
        # Build the Row first, then attach the remove handler so the
        # closure can capture ``row``.
        row = ft.Row(
            controls=[date_cell, name_cell, amount_cell, edit_btn],
            spacing=0,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )
        remove_btn = ft.Semantics(
            button=True,
            label=f"Remove one-off {txn.name}",
            content=ft.IconButton(
                icon=ft.Icons.DELETE_OUTLINE,
                icon_size=16,
                icon_color=tokens.INK_3,
                tooltip="Remove one-off",
                on_click=lambda _, i=idx, r=row: self._remove_one_off(i, r),
            ),
        )
        row.controls.append(remove_btn)

        return ft.Container(
            content=row,
            padding=ft.Padding.symmetric(vertical=10),
            border=ft.Border(top=ft.BorderSide(1, tokens.RULE)) if idx > 0 else None,
        )

    def _rebuild_oneoff_rows(self) -> None:
        rows = [self._oneoff_row(i, txn) for i, txn in enumerate(self._one_offs)]
        self._oneoff_list.controls = rows
        try:
            self._oneoff_list.update()
        except RuntimeError:
            pass
        self._update_oneoff_empty_state(empty=not rows)

    # ------------------------------------------------------------------
    # Recurring rows
    # ------------------------------------------------------------------

    def _on_override_change(self, name: str, original_amount: float, value: str) -> None:
        try:
            new_amount = float(value)
            new_amount = -abs(new_amount) if original_amount < 0 else abs(new_amount)
            self._prefs.set_amount_override(name, new_amount)
        except ValueError:
            self._prefs.clear_amount_override(name)
        self._on_change()

    def _reset_override(self, name: str) -> None:
        self._prefs.clear_amount_override(name)
        self._rebuild_override_rows()
        self._on_change()

    def _on_exclude_toggle(self, e: ft.Event[ft.Checkbox], name: str) -> None:
        included = e.control.value
        self._prefs.set_recurring_excluded(name, excluded=not included)
        self._rebuild_override_rows()
        self._on_change()

    def _recurring_row(
        self,
        item: RecurringItem,
        *,
        is_excluded: bool,
        is_overridden: bool,
        current_amount: float,
        next_date_str: str,
        index: int,
    ) -> ft.Control:
        is_income = item.amount > 0
        amount_signal = tokens.SIGNAL_POSITIVE if is_income else tokens.SIGNAL_NEGATIVE
        # When the row is overridden, the AMOUNT column shows the *original*
        # detected value — dim it to INK_3 with a line-through so the user
        # can see "this was the calculated value, now superseded." The
        # active value lives in the OVERRIDE field, which gets a coral
        # border below to mark it as active.
        amount_color = tokens.INK_3 if (is_excluded or is_overridden) else amount_signal
        name_color = tokens.INK_3 if is_excluded else tokens.INK

        checkbox = ft.Checkbox(
            value=not is_excluded,
            on_change=lambda e, n=item.name: self._on_exclude_toggle(e, n),
            tooltip=f"{'Exclude' if not is_excluded else 'Include'} {item.name} from forecast",
            active_color=tokens.CORAL,
            check_color=tokens.PAPER,
            scale=0.92,
        )

        arrow = ft.Icon(
            ft.Icons.ARROW_UPWARD if is_income else ft.Icons.ARROW_DOWNWARD,
            color=tokens.INK_3 if is_excluded else amount_signal,
            size=14,
            semantics_label=("income" if is_income else "expense"),
        )

        name_text = ft.Text(
            item.name,
            style=ft.TextStyle(
                font_family=tokens.FONT_BODY,
                size=13,
                weight=ft.FontWeight.W_600,
                color=name_color,
                height=1.3,
            ),
            max_lines=1,
            overflow=ft.TextOverflow.ELLIPSIS,
        )

        freq_cell = ft.Container(
            content=_frequency_chip(item.frequency),
            width=_RC_FREQ_W,
            alignment=ft.Alignment(-1, 0),
        )

        next_text = ft.Container(
            content=ft.Text(
                f"Next {next_date_str}" if next_date_str != "–" else next_date_str,
                style=ft.TextStyle(
                    font_family=tokens.FONT_BODY,
                    size=12,
                    weight=ft.FontWeight.W_500,
                    color=tokens.INK_3,
                    height=1.3,
                ),
            ),
            width=_RC_NEXT_W,
            alignment=ft.Alignment(-1, 0),
        )

        amount_text_style = ft.TextStyle(
            font_family=tokens.FONT_BODY,
            size=13,
            weight=ft.FontWeight.W_600,
            color=amount_color,
            height=1.3,
            decoration=ft.TextDecoration.LINE_THROUGH if is_overridden else None,
        )
        amount_sr = (
            f"original {'plus' if is_income else 'minus'} ${abs(item.amount):,.2f}"
            if is_overridden
            else f"{'plus' if is_income else 'minus'} ${abs(item.amount):,.2f}"
        )
        amount_text = ft.Container(
            content=ft.Text(
                f"{_signed_glyph(item.amount)} ${abs(item.amount):,.2f}",
                style=amount_text_style,
                semantics_label=amount_sr,
                tooltip=(
                    f"Original calculated amount: ${abs(item.amount):,.2f}"
                    if is_overridden
                    else None
                ),
            ),
            width=_RC_AMOUNT_W,
            alignment=ft.Alignment(1, 0),
        )

        # Override field — coral 2px border when active so the user can see
        # at a glance which value the forecast is actually using.
        override_field = _ledger_field(
            value=f"{abs(current_amount):.2f}",
            width=_RC_OVERRIDE_W,
            keyboard_type=ft.KeyboardType.NUMBER,
            on_submit=lambda e, n=item.name, a=item.amount: self._on_override_change(
                n, a, e.control.value or ""
            ),
            dense=True,
            tooltip=(
                f"Active override for {item.name}"
                if is_overridden
                else f"Override {item.name} amount for this period"
            ),
            border_color=tokens.CORAL if is_overridden else None,
            border_width=2 if is_overridden else None,
        )
        override_field.visible = not is_excluded
        override_field.prefix = ft.Text(
            "$",
            style=ft.TextStyle(font_family=tokens.FONT_BODY, size=12, color=tokens.INK_2),
        )

        reset_btn = ft.Semantics(
            button=True,
            label=f"Reset {item.name} to original amount",
            visible=is_overridden and not is_excluded,
            content=ft.IconButton(
                icon=ft.Icons.RESTORE,
                icon_size=16,
                icon_color=tokens.INK_3,
                tooltip="Reset to original",
                on_click=lambda _, n=item.name: self._reset_override(n),
            ),
        )

        row = ft.Row(
            controls=[
                ft.Container(content=checkbox, width=_RC_CHECK_W, alignment=ft.Alignment(0, 0)),
                ft.Container(content=arrow, width=_RC_ARROW_W, alignment=ft.Alignment(0, 0)),
                ft.Container(content=name_text, width=_RC_NAME_W),
                freq_cell,
                next_text,
                amount_text,
                ft.Container(
                    content=override_field,
                    width=_RC_OVERRIDE_W,
                    alignment=ft.Alignment(1, 0),
                ),
                reset_btn,
            ],
            spacing=8,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

        return ft.Container(
            content=row,
            padding=ft.Padding.symmetric(vertical=10),
            border=ft.Border(top=ft.BorderSide(1, tokens.RULE)) if index > 0 else None,
        )

    def _rebuild_override_rows(self) -> None:
        excluded = self._prefs.excluded_recurring_names
        matching: list[tuple[int, RecurringItem]] = []
        other_account: list[tuple[int, RecurringItem]] = []
        for i, item in enumerate(self._recurring_items):
            if (
                self._selected_account_id
                and item.account_id
                and item.account_id != self._selected_account_id
            ):
                other_account.append((i, item))
            else:
                matching.append((i, item))

        overrides = self._prefs.amount_overrides
        included_count = 0
        rows: list[ft.Control] = []

        from src.utils.date_helpers import next_occurrence

        today = date.today()
        for idx, (_orig_i, item) in enumerate(matching):
            is_excluded = item.name in excluded
            is_overridden = item.name in overrides
            current_amount = overrides.get(item.name, item.amount)
            if not is_excluded:
                included_count += 1

            next_date = next_occurrence(item.base_date, item.frequency, today)
            next_date_str = next_date.strftime("%b %d") if next_date else "–"

            rows.append(
                self._recurring_row(
                    item,
                    is_excluded=is_excluded,
                    is_overridden=is_overridden,
                    current_amount=current_amount,
                    next_date_str=next_date_str,
                    index=idx,
                )
            )

        if not rows:
            rows.append(
                ft.Container(
                    content=ft.Text(
                        "No recurring items detected for this account yet.",
                        style=ft.TextStyle(
                            font_family=tokens.FONT_BODY,
                            size=12,
                            color=tokens.INK_3,
                            italic=True,
                            height=1.4,
                        ),
                    ),
                    padding=ft.Padding.symmetric(vertical=16),
                )
            )

        # Meta pill (e.g. "3 of 12 included") on the section header.
        total_matching = len(matching)
        self._recurring_meta_text.value = f"{included_count} of {total_matching} included"
        try:
            self._recurring_meta_text.update()
        except (RuntimeError, AssertionError):
            pass

        # "Hidden from other accounts" note, only when applicable.
        if other_account:
            n = len(other_account)
            self._recurring_other_account_note.content = ft.Container(
                content=ft.Text(
                    f"{n} item{'s' if n != 1 else ''} from other accounts are hidden.",
                    style=ft.TextStyle(
                        font_family=tokens.FONT_BODY,
                        size=12,
                        color=tokens.INK_3,
                        italic=True,
                        height=1.4,
                    ),
                ),
                padding=ft.Padding.only(top=12),
            )
        else:
            self._recurring_other_account_note.content = None
        try:
            self._recurring_other_account_note.update()
        except (RuntimeError, AssertionError):
            pass

        self._override_list.controls = rows
        try:
            self._override_list.update()
        except RuntimeError:
            pass
