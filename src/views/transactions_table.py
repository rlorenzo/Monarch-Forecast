"""Editorial day-block ledger for upcoming transactions.

The Transactions tab is the chart's text equivalent and the screen-reader
fallback, but it is also the longest planning surface in the app — the
view a user sits with when they want to see exactly what's coming. So it
is shaped as a typographic ledger: each day is a small chapter with a
serif date in a left gutter, transactions stacked in tabular Inter rows
on the right, and a per-day net summary tucked under the date. The
running balance lives in the right-most column and turns ``signal-negative``
on any row that breaches the safety threshold.

A filter strip sits above the ledger: a search input plus type-toggle
chips (``All / Income / Expense / One-Off / Card``). The strip is owned
by ``TransactionsView`` so its controls survive forecast rebuilds and
the search input keeps focus across keystrokes.

Public API:

- ``build_transactions_table(result, on_edit_cc=, on_edit_oneoff=,
  on_edit_recurring=)`` → ``ft.Control`` — the unfiltered ledger. Kept
  as the public entry point so the accessibility regression test in
  ``tests/test_accessibility.py`` still has a no-state builder to walk.
- ``TransactionsView(on_edit_cc=, on_edit_oneoff=, on_edit_recurring=)``
  — the stateful Column with filter strip + ledger. Dashboard holds an
  instance and drives it via ``set_forecast``.
- ``build_ledger_header()`` — the column header on its own, for the
  dashboard's combined Both ledger.

Display order is a dashboard-level setting (oldest-first by default,
persisted in preferences.json) passed down as ``newest_first`` so this
ledger and the Recent one always run the same direction.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import date

import flet as ft

from src.data.models import ForecastTransaction
from src.forecast.models import ForecastDay, ForecastResult
from src.views import tokens

# Body column widths. The sticky header uses the same widths so columns
# lock vertically across the scroll region.
_GUTTER_WIDTH = 92
_GUTTER_GAP = 16
_COL_DESC = 320
_COL_TYPE = 160
_COL_AMOUNT = 140
_COL_BALANCE = 130
_ROW_VERT_PAD = 9

# Filter chip identifiers — internal state values.
_FILTER_ALL = "all"
_FILTER_INCOME = "income"
_FILTER_EXPENSE = "expense"
_FILTER_ONEOFF = "oneoff"
_FILTER_CC = "cc"

_FILTER_DEFS: list[tuple[str, str]] = [
    (_FILTER_ALL, "All"),
    (_FILTER_INCOME, "Income"),
    (_FILTER_EXPENSE, "Expense"),
    (_FILTER_ONEOFF, "One-off"),
    (_FILTER_CC, "Card payment"),
]


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def _is_oneoff(txn: ForecastTransaction) -> bool:
    return txn.category == "Adjustment"


def _is_cc(txn: ForecastTransaction) -> bool:
    return txn.category == "Credit Card Payment"


def _money(amount: float) -> str:
    """Format a positive amount with thousands separators and 2dp."""
    return f"${abs(amount):,.2f}"


def _signed_glyph(amount: float) -> str:
    """True minus (U+2212) for negatives, plus for positives. Avoids the
    hyphen-minus, which renders narrower than the plus and unbalances the
    column."""
    return "−" if amount < 0 else "+"


# ---------------------------------------------------------------------------
# Cell builders
# ---------------------------------------------------------------------------


def _amount_cell(amount: float) -> ft.Text:
    is_negative = amount < 0
    color = tokens.SIGNAL_NEGATIVE if is_negative else tokens.SIGNAL_POSITIVE
    sr = f"{'minus' if is_negative else 'plus'} {_money(amount)}"
    return ft.Text(
        f"{_signed_glyph(amount)} {_money(amount)}",
        style=ft.TextStyle(
            font_family=tokens.FONT_BODY,
            size=13,
            weight=ft.FontWeight.W_600,
            color=color,
            height=1.3,
        ),
        semantics_label=sr,
    )


def _balance_cell(balance: float, breach: bool) -> ft.Control:
    """Running balance. On breach: ``signal-negative`` color, bold weight,
    and a leading true-minus on negative values. The negative glyph + bold
    weight + signal-negative color together carry the meaning so the
    color-only rule is honored without a decorative warning icon.
    """
    is_negative = balance < 0
    color = tokens.SIGNAL_NEGATIVE if breach else tokens.INK
    weight = ft.FontWeight.W_700 if breach else ft.FontWeight.W_500
    display = f"−${abs(balance):,.2f}" if is_negative else f"${balance:,.2f}"
    return ft.Text(
        display,
        style=ft.TextStyle(
            font_family=tokens.FONT_BODY,
            size=13,
            weight=weight,
            color=color,
            height=1.3,
        ),
        semantics_label=(
            f"running balance ${balance:,.2f}" + (", below safety threshold" if breach else "")
        ),
        text_align=ft.TextAlign.RIGHT,
    )


def _type_cell(txn: ForecastTransaction) -> ft.Control:
    """Category label. Every row uses the same quiet UPPERCASE label —
    chips are reserved for the filter strip. The pencil at the row's
    right edge is the editable affordance, so a chip would be duplicate
    signal.

    The internal ``"Adjustment"`` category is relabeled to ``"ONE-OFF"``
    so the display reads in user language, not system language.
    """
    if _is_oneoff(txn):
        label = "ONE-OFF"
    elif _is_cc(txn):
        label = "CARD PAYMENT"
    else:
        label = (txn.category or "RECURRING").upper()
    return ft.Text(
        label,
        style=ft.TextStyle(
            font_family=tokens.FONT_BODY,
            size=11,
            weight=ft.FontWeight.W_500,
            color=tokens.INK_3,
            letter_spacing=0.4,
            height=1.3,
        ),
        max_lines=1,
        overflow=ft.TextOverflow.ELLIPSIS,
    )


def _edit_button(
    txn: ForecastTransaction,
    on_edit_cc: Callable[[ForecastTransaction], None] | None,
    on_edit_oneoff: Callable[[ForecastTransaction], None] | None,
    on_edit_recurring: Callable[[ForecastTransaction], None] | None,
) -> ft.Control | None:
    """Per-row pencil. Always wrapped in ``ft.Semantics(button=True,
    label=…)`` per the accessibility contract — the regression test in
    ``tests/test_accessibility.py`` walks this tree and fails if any
    IconButton lacks a labeled Semantics ancestor."""
    if on_edit_cc is not None and _is_cc(txn):
        return ft.Semantics(
            button=True,
            label=f"Edit payment amount for {txn.name}",
            content=ft.IconButton(
                icon=ft.Icons.EDIT_OUTLINED,
                icon_size=14,
                icon_color=tokens.INK_3,
                tooltip="Edit payment amount",
                on_click=lambda _, t=txn: on_edit_cc(t),
            ),
        )
    if on_edit_oneoff is not None and _is_oneoff(txn):
        return ft.Semantics(
            button=True,
            label=f"Edit one-off {txn.name}",
            content=ft.IconButton(
                icon=ft.Icons.EDIT_OUTLINED,
                icon_size=14,
                icon_color=tokens.INK_3,
                tooltip="Edit amount",
                on_click=lambda _, t=txn: on_edit_oneoff(t),
            ),
        )
    if on_edit_recurring is not None and txn.is_recurring:
        return ft.Semantics(
            button=True,
            label=f"Override amount for recurring {txn.name}",
            content=ft.IconButton(
                icon=ft.Icons.EDIT_OUTLINED,
                icon_size=14,
                icon_color=tokens.INK_3,
                tooltip="Override amount",
                on_click=lambda _, t=txn: on_edit_recurring(t),
            ),
        )
    return None


# ---------------------------------------------------------------------------
# Row + day-block + gutter
# ---------------------------------------------------------------------------


def _txn_row(
    txn: ForecastTransaction,
    running_balance: float,
    breach: bool,
    on_edit_cc: Callable[[ForecastTransaction], None] | None,
    on_edit_oneoff: Callable[[ForecastTransaction], None] | None,
    on_edit_recurring: Callable[[ForecastTransaction], None] | None,
) -> ft.Control:
    edit_btn = _edit_button(txn, on_edit_cc, on_edit_oneoff, on_edit_recurring)

    name = ft.Text(
        txn.name,
        style=tokens.body_style(tokens.INK),
        max_lines=1,
        overflow=ft.TextOverflow.ELLIPSIS,
    )

    amount = _amount_cell(txn.amount)
    # Reserve a constant 22px slot on the right of the amount so columns
    # don't reflow when an editable row sits next to a non-editable one.
    if edit_btn is not None:
        amount_block = ft.Row(
            controls=[amount, edit_btn],
            spacing=2,
            tight=True,
            alignment=ft.MainAxisAlignment.END,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )
    else:
        amount_block = ft.Row(
            controls=[amount, ft.Container(width=22)],
            spacing=2,
            tight=True,
            alignment=ft.MainAxisAlignment.END,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

    return ft.Container(
        content=ft.Row(
            controls=[
                ft.Container(content=name, width=_COL_DESC),
                ft.Container(content=_type_cell(txn), width=_COL_TYPE),
                ft.Container(
                    content=amount_block,
                    width=_COL_AMOUNT,
                    alignment=ft.Alignment(1, 0),
                ),
                ft.Container(
                    content=_balance_cell(running_balance, breach),
                    width=_COL_BALANCE,
                    alignment=ft.Alignment(1, 0),
                ),
            ],
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=0,
        ),
        padding=ft.Padding.symmetric(vertical=_ROW_VERT_PAD),
    )


def _day_gutter(
    day_date: date,
    today: date,
    visible_net: float,
    visible_count: int,
) -> ft.Control:
    """The left gutter for a day-block.

    Layout: a 2px coral marker (or transparent placeholder), then a Column
    holding the UPPERCASE month/day label, the Fraunces weekday, and the
    net + count. The marker is reserved by a transparent same-width
    Container on non-today rows so the date never shifts horizontally.
    """
    is_today = day_date == today

    eyebrow = ft.Text(
        day_date.strftime("%b %d").upper(),
        style=ft.TextStyle(
            font_family=tokens.FONT_BODY,
            size=11,
            weight=ft.FontWeight.W_600,
            color=tokens.CORAL if is_today else tokens.INK_2,
            letter_spacing=0.66,
            height=1.2,
        ),
    )
    weekday = ft.Text(
        day_date.strftime("%a"),
        style=ft.TextStyle(
            font_family=tokens.FONT_DISPLAY,
            font_family_fallback=["Source Serif Pro", "Georgia", "serif"],
            size=22,
            weight=ft.FontWeight.W_500,
            color=tokens.INK if is_today else tokens.INK_2,
            letter_spacing=-0.2,
            height=1.05,
        ),
    )

    # The net summary only appears when the day has multiple transactions
    # — on single-txn days, the net IS the transaction (it sits one row
    # right of the gutter), so showing it twice is duplicate signal. The
    # ``NET`` eyebrow disambiguates the floating dollar figure from a
    # balance or transaction amount.
    if visible_count <= 1:
        net_block: ft.Control = ft.Container(height=0)
    else:
        is_neg = visible_net < 0
        net_color = tokens.SIGNAL_NEGATIVE if is_neg else tokens.SIGNAL_POSITIVE
        net_eyebrow = ft.Text(
            "NET",
            style=ft.TextStyle(
                font_family=tokens.FONT_BODY,
                size=11,
                weight=ft.FontWeight.W_600,
                color=tokens.INK_3,
                letter_spacing=0.66,
                height=1.2,
            ),
        )
        net_text = ft.Text(
            f"{_signed_glyph(visible_net)}${abs(visible_net):,.0f}",
            style=ft.TextStyle(
                font_family=tokens.FONT_BODY,
                size=12,
                weight=ft.FontWeight.W_600,
                color=net_color,
                height=1.2,
            ),
            semantics_label=(
                f"day net {'negative' if is_neg else 'positive'} ${abs(visible_net):,.2f}"
            ),
        )
        count_label = ft.Text(
            f"{visible_count} txns",
            style=ft.TextStyle(
                font_family=tokens.FONT_BODY,
                size=11,
                weight=ft.FontWeight.W_400,
                color=tokens.INK_3,
                height=1.2,
            ),
        )
        net_block = ft.Column(
            controls=[net_eyebrow, net_text, count_label],
            spacing=1,
            tight=True,
        )

    marker_color = tokens.CORAL if is_today else "transparent"
    marker = ft.Container(
        width=2,
        height=22,
        bgcolor=marker_color,
        border_radius=ft.BorderRadius.all(1),
    )

    inner = ft.Column(
        controls=[
            eyebrow,
            weekday,
            ft.Container(height=8),
            net_block,
        ],
        spacing=2,
        tight=True,
    )

    return ft.Container(
        content=ft.Row(
            controls=[marker, ft.Container(width=8), inner],
            spacing=0,
            tight=True,
            vertical_alignment=ft.CrossAxisAlignment.START,
        ),
        width=_GUTTER_WIDTH,
        padding=ft.Padding.only(top=_ROW_VERT_PAD),
    )


def _day_block(
    day: ForecastDay,
    starting_balance: float,
    safety_threshold: float,
    today: date,
    should_show: Callable[[ForecastTransaction], bool] | None,
    on_edit_cc: Callable[[ForecastTransaction], None] | None,
    on_edit_oneoff: Callable[[ForecastTransaction], None] | None,
    on_edit_recurring: Callable[[ForecastTransaction], None] | None,
    is_first: bool,
) -> tuple[ft.Container | None, float]:
    """Build one day-block.

    Returns ``(control, running_balance_after_day)`` or ``(None, ...)`` if
    every transaction was filtered out — the running balance still
    accumulates correctly across hidden rows so the visible balance
    figures match the underlying projection.
    """
    txn_rows: list[ft.Control] = []
    running = starting_balance
    visible_net = 0.0
    visible_count = 0

    for txn in day.transactions:
        running += txn.amount
        if should_show is not None and not should_show(txn):
            continue
        breach = running < safety_threshold
        visible_net += txn.amount
        visible_count += 1
        txn_rows.append(
            _txn_row(
                txn,
                running,
                breach,
                on_edit_cc,
                on_edit_oneoff,
                on_edit_recurring,
            )
        )

    if not txn_rows:
        return None, running

    body = ft.Column(controls=txn_rows, spacing=0, tight=True, expand=True)

    block = ft.Container(
        content=ft.Row(
            controls=[
                _day_gutter(day.date, today, visible_net, visible_count),
                ft.Container(width=_GUTTER_GAP),
                body,
            ],
            spacing=0,
            vertical_alignment=ft.CrossAxisAlignment.START,
            expand=True,
        ),
        padding=ft.Padding.only(top=2, bottom=10),
        # Top hairline above every block except the first; the ledger
        # header already provides the upper rule for the first one.
        border=(None if is_first else ft.Border(top=ft.BorderSide(1, tokens.RULE))),
    )
    return block, running


# ---------------------------------------------------------------------------
# Header + empty states
# ---------------------------------------------------------------------------


def _column_label_style(color: str) -> ft.TextStyle:
    """Shared type for every ledger column header. Only the ink varies:
    ``INK_3`` for a plain label, ``INK_2`` for the sortable DATE header so
    the one clickable column reads a shade heavier than its neighbours."""
    return ft.TextStyle(
        font_family=tokens.FONT_BODY,
        size=11,
        weight=ft.FontWeight.W_600,
        color=color,
        letter_spacing=0.66,
        height=1.2,
    )


def _column_label(text: str, width: int, *, align_right: bool = False) -> ft.Control:
    label = ft.Text(text, style=_column_label_style(tokens.INK_3))
    return ft.Container(
        content=label,
        width=width,
        alignment=ft.Alignment(1, 0) if align_right else ft.Alignment(-1, 0),
    )


def _build_search_field(
    *,
    label: str,
    hint_text: str,
    on_change: Callable[[ft.Event[ft.TextField]], None],
    tooltip: str,
    width: int = 320,
) -> ft.TextField:
    """Search input shared by the Upcoming and Recent transaction ledgers.

    Only the copy (label / hint / tooltip) differs between the two ledgers;
    the paper-and-ink styling is identical, so both build from here.
    """
    return ft.TextField(
        label=label,
        label_style=ft.TextStyle(
            font_family=tokens.FONT_BODY,
            size=12,
            color=tokens.INK_2,
        ),
        hint_text=hint_text,
        prefix_icon=ft.Icons.SEARCH,
        on_change=on_change,
        dense=True,
        border_color=tokens.RULE,
        focused_border_color=tokens.CORAL,
        border_width=1,
        focused_border_width=2,
        bgcolor=tokens.PAPER,
        color=tokens.INK,
        text_size=13,
        hint_style=ft.TextStyle(
            font_family=tokens.FONT_BODY,
            size=13,
            color=tokens.INK_3,
        ),
        content_padding=ft.Padding.symmetric(horizontal=12, vertical=10),
        width=width,
        tooltip=tooltip,
    )


class _SortableDateLabel(ft.Container):
    """The DATE column label, doubling as the ledger's sort control.

    A Container rather than a Button for the same reason ``_FilterChip``
    is one: ``on_click`` lands directly and nothing of Material's chrome
    comes with it, so the control reads as a column header rather than as
    a widget parked in the header.
    """

    def __init__(self, *, newest_first: bool, on_toggle: Callable[[], None]) -> None:
        self._on_toggle = on_toggle
        self._label = ft.Text(
            # ↑ ascending (oldest at the top), ↓ descending. The glyph is
            # never the only signal — the Semantics label below spells the
            # order out, per the color/glyph rule in AGENTS.md.
            f"DATE {'↓' if newest_first else '↑'}",
            style=_column_label_style(tokens.INK_2),
        )
        super().__init__(
            content=self._label,
            width=_GUTTER_WIDTH,
            alignment=ft.Alignment(-1, 0),
            on_click=self._handle_click,
            on_hover=self._handle_hover,
            tooltip=(
                "Sorted newest first — click for oldest first"
                if newest_first
                else "Sorted oldest first — click for newest first"
            ),
        )

    def _handle_click(self, _e: ft.Event[ft.Container]) -> None:
        self._on_toggle()

    def _handle_hover(self, e: ft.Event[ft.Container]) -> None:
        # Swap the whole style rather than setting ``Text.color``: the
        # color lives inside ``style``, and a bare ``color=`` alongside a
        # style that also carries one is ambiguous on Flet's Dart side.
        ink = tokens.CORAL_DEEP if e.data == "true" else tokens.INK_2
        self._label.style = _column_label_style(ink)
        try:
            self.update()
        except (RuntimeError, AssertionError):
            pass


def build_date_column_label(
    *,
    newest_first: bool = False,
    on_toggle_order: Callable[[], None] | None = None,
) -> ft.Control:
    """DATE header cell — a sort toggle when ``on_toggle_order`` is given,
    a plain label otherwise.

    Sorting lives on the column it reorders instead of in its own chip
    row, which keeps a full row of vertical space for the ledger. The
    plain-label fallback keeps the no-state builders free of click
    targets for the accessibility walk.
    """
    if on_toggle_order is None:
        return _column_label("DATE", _GUTTER_WIDTH)
    order = "newest first" if newest_first else "oldest first"
    other = "oldest first" if newest_first else "newest first"
    return ft.Semantics(
        button=True,
        label=f"Sort by date, currently {order}. Activate to sort {other}.",
        content=_SortableDateLabel(newest_first=newest_first, on_toggle=on_toggle_order),
    )


def build_ledger_header(
    *,
    newest_first: bool = False,
    on_toggle_order: Callable[[], None] | None = None,
) -> ft.Control:
    """The projected ledger's column header.

    Public because the dashboard's combined Both ledger hoists a single
    header to the very top of the column — whichever section (past or
    projected) leads under the active sort order — instead of letting the
    projected view carry one into the middle of the timeline.
    """
    return ft.Container(
        content=ft.Row(
            controls=[
                ft.Container(
                    width=_GUTTER_WIDTH + _GUTTER_GAP,
                    content=build_date_column_label(
                        newest_first=newest_first, on_toggle_order=on_toggle_order
                    ),
                ),
                _column_label("DESCRIPTION", _COL_DESC),
                _column_label("CATEGORY", _COL_TYPE),
                _column_label("AMOUNT", _COL_AMOUNT, align_right=True),
                _column_label("BALANCE", _COL_BALANCE, align_right=True),
            ],
            spacing=0,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        padding=ft.Padding.only(bottom=10, top=4),
        border=ft.Border(bottom=ft.BorderSide(1, tokens.RULE)),
    )


def _empty_state(headline: str, hint: str) -> ft.Control:
    return ft.Container(
        content=ft.Column(
            controls=[
                ft.Text(
                    headline,
                    style=tokens.headline_style(tokens.INK_2),
                    text_align=ft.TextAlign.CENTER,
                ),
                ft.Text(
                    hint,
                    style=tokens.body_style(tokens.INK_3),
                    text_align=ft.TextAlign.CENTER,
                ),
            ],
            spacing=8,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            tight=True,
        ),
        padding=ft.Padding.symmetric(vertical=72),
        alignment=ft.Alignment(0, 0),
    )


# ---------------------------------------------------------------------------
# Public builder (no filter UI — kept stable for the a11y test)
# ---------------------------------------------------------------------------


def build_transactions_table(
    result: ForecastResult,
    on_edit_cc: Callable[[ForecastTransaction], None] | None = None,
    on_edit_oneoff: Callable[[ForecastTransaction], None] | None = None,
    on_edit_recurring: Callable[[ForecastTransaction], None] | None = None,
    *,
    today: date | None = None,
    should_show: Callable[[ForecastTransaction], bool] | None = None,
    empty_headline: str = "No transactions in this window.",
    empty_hint: str = "Add a one-off from the Adjustments tab, or extend the forecast window.",
    newest_first: bool = False,
    show_header: bool = True,
    on_toggle_order: Callable[[], None] | None = None,
) -> ft.Control:
    """Build the editorial day-block ledger.

    Args:
        result: Forecast to render.
        on_edit_cc: Optional click handler for the per-row pencil on a
            credit-card-payment row.
        on_edit_oneoff: Optional click handler for the pencil on a one-off
            (Adjustment) row.
        on_edit_recurring: Optional click handler for the pencil on a
            recurring row.
        today: The "today" date used for the coral marker on the matching
            day-block. Defaults to ``date.today()``; tests pass an explicit
            value for determinism.
        should_show: Optional predicate that returns True for transactions
            that should be rendered. Hidden transactions still contribute
            to the running balance so visible figures stay accurate.
        empty_headline / empty_hint: Copy used when no rows are visible —
            either the forecast contains no transactions, or the filter
            hides them all.
        newest_first: Display order. False (the default) reads oldest
            day first, like a statement; True is checkbook-register
            order with the furthest projected day on top. Running
            balances always accumulate chronologically either way.
        show_header: Render the column header above the first day block.
            The combined Both ledger sets this False and hoists a single
            ``build_ledger_header()`` to the top of its own column, so the
            header can't land mid-timeline when the past section leads.
        on_toggle_order: Makes the DATE header a sort toggle. Omitted, the
            header is a plain label.
    """
    today_d = today or date.today()
    blocks: list[ft.Control] = (
        [build_ledger_header(newest_first=newest_first, on_toggle_order=on_toggle_order)]
        if show_header
        else []
    )

    # Balances always accumulate chronologically; only the DISPLAY order
    # flips. Oldest-first (the default) reads like a statement — today at
    # the top, the forecast unfolding downward. Newest-first is
    # checkbook-register order, the furthest projected day leading. In the
    # combined Both view the dashboard stacks the past and projected
    # sections to match, so the TODAY line always sits mid-timeline.
    running = result.starting_balance
    day_blocks: list[ft.Container] = []
    for day in result.days:
        if not day.transactions:
            continue
        block, running = _day_block(
            day,
            running,
            result.safety_threshold,
            today_d,
            should_show,
            on_edit_cc,
            on_edit_oneoff,
            on_edit_recurring,
            is_first=False,
        )
        if block is None:
            continue
        day_blocks.append(block)

    if newest_first:
        day_blocks.reverse()
    if day_blocks:
        # The header already rules the top edge; the first rendered block
        # doesn't need its own hairline.
        day_blocks[0].border = None
        blocks.extend(day_blocks)
    else:
        blocks.append(_empty_state(empty_headline, empty_hint))

    return ft.Column(controls=blocks, spacing=0, tight=True)


# ---------------------------------------------------------------------------
# Stateful view: filter strip + ledger
# ---------------------------------------------------------------------------


class _FilterChip(ft.Container):
    """A toggle-able filter chip styled per DESIGN.md ``chip-recurring``.

    Container is the right primitive here — ``on_click`` lands directly,
    bg/text/border can swap on selection, and we avoid pulling in
    ``ft.Chip``'s Material chrome which clashes with the paper-and-ink
    palette.
    """

    def __init__(
        self,
        *,
        label: str,
        value: str,
        selected: bool,
        on_select: Callable[[str], None],
    ) -> None:
        self._value = value
        self._selected = selected
        self._on_select = on_select

        self._label = ft.Text(
            label,
            style=ft.TextStyle(
                font_family=tokens.FONT_BODY,
                size=12,
                weight=ft.FontWeight.W_600,
                color=tokens.CORAL_DEEP if selected else tokens.INK_2,
                height=1.2,
            ),
        )

        super().__init__(
            content=self._label,
            bgcolor=tokens.CORAL_TINT if selected else tokens.PAPER,
            padding=ft.Padding.symmetric(horizontal=12, vertical=8),
            border_radius=ft.BorderRadius.all(999),  # pill — small, fine in product
            border=ft.Border.all(
                1,
                "transparent" if selected else tokens.RULE,
            ),
            on_click=self._handle_click,
            on_hover=self._handle_hover,
            tooltip=f"Filter: {label}",
            animate_scale=ft.Animation(150, ft.AnimationCurve.EASE_OUT_QUART),
        )

    def _handle_click(self, _e: ft.Event[ft.Container]) -> None:
        self._on_select(self._value)

    def _handle_hover(self, e: ft.Event[ft.Container]) -> None:
        if self._selected:
            return
        is_in = e.data == "true"
        self.bgcolor = tokens.PAPER_2 if is_in else tokens.PAPER
        try:
            self.update()
        except (RuntimeError, AssertionError):
            pass


def build_filter_chip(
    *,
    label: str,
    value: str,
    selected: bool,
    on_select: Callable[[str], None],
    sr_prefix: str = "Filter",
) -> ft.Control:
    """A ``_FilterChip`` wrapped in labeled ``Semantics``.

    Chips are Containers, which screen readers don't announce as
    interactive on Flet desktop; the wrapper carries the accessible name
    and selection state, mirroring the icon-button contract in
    AGENTS.md. Chips rebuild on every selection change, so the label's
    ", selected" suffix stays current.
    """
    return ft.Semantics(
        button=True,
        label=f"{sr_prefix}: {label}" + (", selected" if selected else ""),
        content=_FilterChip(label=label, value=value, selected=selected, on_select=on_select),
    )


class TransactionsView(ft.Column):
    """Filter strip + ledger.

    Owns its own search/filter state so the search input keeps focus
    across forecast rebuilds. The dashboard creates one instance and
    drives it with ``set_forecast(result)`` whenever a recompute
    finishes.
    """

    def __init__(
        self,
        *,
        on_edit_cc: Callable[[ForecastTransaction], None] | None = None,
        on_edit_oneoff: Callable[[ForecastTransaction], None] | None = None,
        on_edit_recurring: Callable[[ForecastTransaction], None] | None = None,
        newest_first: bool = False,
        on_toggle_order: Callable[[], None] | None = None,
    ) -> None:
        super().__init__()
        self._on_toggle_order = on_toggle_order
        self._on_edit_cc = on_edit_cc
        self._on_edit_oneoff = on_edit_oneoff
        self._on_edit_recurring = on_edit_recurring
        self._newest_first = newest_first
        # False only inside the combined Both ledger, which hoists one
        # shared header to the top of its column.
        self._show_header = True

        self._forecast: ForecastResult | None = None
        self._search: str = ""
        self._filter: str = _FILTER_ALL
        self._rebuild_seq = 0  # Debounce token for search-driven rebuilds.

        # --- Search input -------------------------------------------------
        self._search_field = _build_search_field(
            label="Search transactions",
            hint_text="Search description",
            on_change=self._on_search_change,
            tooltip="Filter transactions by description",
        )

        # --- Chip strip ---------------------------------------------------
        self._chip_row = ft.Row(spacing=8, wrap=True, run_spacing=8)
        self._rebuild_chips()

        # Row holding [search] [chips]. wrap=True so narrow widths stack.
        self._filter_strip = ft.Container(
            content=ft.Row(
                controls=[
                    self._search_field,
                    ft.Container(width=16),
                    self._chip_row,
                ],
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                wrap=True,
                run_spacing=12,
            ),
            padding=ft.Padding.only(bottom=8),
        )

        self._ledger_container = ft.Container()

        self.spacing = 12
        self.controls = [self._filter_strip, self._ledger_container]

    # ---- Public API -----------------------------------------------------

    def set_forecast(self, result: ForecastResult) -> None:
        self._forecast = result
        self._rebuild_ledger()

    def set_newest_first(self, newest_first: bool) -> None:
        """Flip the display order. The dashboard drives this whenever the
        DATE header is clicked — in any ledger — so all of them agree."""
        if self._newest_first == newest_first:
            return
        self._newest_first = newest_first
        self._rebuild_ledger()

    def set_show_header(self, show_header: bool) -> None:
        """Hide this view's own column header. The combined Both ledger
        renders one at the top of its column instead."""
        if self._show_header == show_header:
            return
        self._show_header = show_header
        self._rebuild_ledger()

    def clear(self) -> None:
        """Drop the rendered ledger — used when the dashboard has no
        forecast to show (no accounts, fatal load error)."""
        self._forecast = None
        self._rebuild_ledger()

    # ---- State handlers -------------------------------------------------

    def _on_search_change(self, e: ft.Event[ft.TextField]) -> None:
        self._search = (e.control.value or "").strip().lower()
        self._schedule_ledger_rebuild()

    def _schedule_ledger_rebuild(self) -> None:
        """Debounce search-driven rebuilds: reconstructing the full ledger
        per keystroke is wasteful at hundreds of rows. Falls back to an
        immediate synchronous rebuild when unmounted (tests, teardown)."""
        self._rebuild_seq += 1
        seq = self._rebuild_seq
        try:
            page = self.page
        except RuntimeError:
            page = None
        if not isinstance(page, ft.Page):
            self._rebuild_ledger()
            return

        async def _later() -> None:
            await asyncio.sleep(0.18)
            if seq == self._rebuild_seq:
                self._rebuild_ledger()

        try:
            page.run_task(_later)
        except (AssertionError, RuntimeError):
            self._rebuild_ledger()

    def _on_chip_select(self, value: str) -> None:
        if self._filter == value:
            return
        self._filter = value
        self._rebuild_chips()
        self._rebuild_ledger()

    def _should_show(self, txn: ForecastTransaction) -> bool:
        if self._search and self._search not in txn.name.lower():
            return False
        if self._filter == _FILTER_INCOME:
            return txn.amount > 0
        if self._filter == _FILTER_EXPENSE:
            return txn.amount < 0
        if self._filter == _FILTER_ONEOFF:
            return _is_oneoff(txn)
        if self._filter == _FILTER_CC:
            return _is_cc(txn)
        return True

    # ---- Rebuilds -------------------------------------------------------

    def _rebuild_chips(self) -> None:
        self._chip_row.controls = [
            build_filter_chip(
                label=label,
                value=value,
                selected=value == self._filter,
                on_select=self._on_chip_select,
            )
            for value, label in _FILTER_DEFS
        ]
        try:
            self._chip_row.update()
        except (RuntimeError, AssertionError):
            pass

    def _rebuild_ledger(self) -> None:
        if self._forecast is None:
            self._ledger_container.content = None
        else:
            empty_headline, empty_hint = self._empty_copy()
            self._ledger_container.content = build_transactions_table(
                self._forecast,
                on_edit_cc=self._on_edit_cc,
                on_edit_oneoff=self._on_edit_oneoff,
                on_edit_recurring=self._on_edit_recurring,
                should_show=self._should_show,
                empty_headline=empty_headline,
                empty_hint=empty_hint,
                newest_first=self._newest_first,
                show_header=self._show_header,
                on_toggle_order=self._on_toggle_order,
            )
        try:
            self._ledger_container.update()
        except (RuntimeError, AssertionError):
            pass

    def _empty_copy(self) -> tuple[str, str]:
        """Empty-state copy that adapts to the active filter."""
        if self._search and self._filter == _FILTER_ALL:
            return (
                "No transactions match that search.",
                f"Nothing in this forecast window matches “{self._search}”.",
            )
        labels = dict(_FILTER_DEFS)
        if self._filter != _FILTER_ALL:
            label = labels[self._filter].lower()
            search_part = f" matching “{self._search}”" if self._search else ""
            return (
                f"No {label} transactions{search_part}.",
                "Clear the filter or extend the forecast window to see more.",
            )
        return (
            "No transactions in this window.",
            "Add a one-off from the Adjustments tab, or extend the forecast window.",
        )

    # ---- Test/escape hatch ---------------------------------------------

    @property
    def search_field(self) -> ft.TextField:
        """Expose the search field so the dashboard can focus it on tab switch."""
        return self._search_field
