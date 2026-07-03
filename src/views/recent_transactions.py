"""Recent completed transactions ledger.

The "Recent" mode of the Transactions tab: where the money actually
went, as opposed to the Upcoming ledger's where it is projected to go.
Renders the raw Monarch transaction history (the same window the
recurring detector consumes), newest day first, using the same editorial
day-block language as the Upcoming ledger. Pending transactions are
excluded so the list reflects completed activity only.

Public API mirrors ``transactions_table``:

- ``parse_history_transactions(raw_txns)`` — normalize raw Monarch
  transaction dicts into ``HistoryTransaction`` records.
- ``build_recent_transactions_table(txns, today=)`` → ``ft.Control`` —
  stateless ledger builder, kept walkable for the accessibility
  regression test.
- ``RecentTransactionsView()`` — stateful Column: search + flow chips +
  period chips + ledger, strictly scoped to the checking account chosen
  in the dashboard dropdown (``set_account_filter``). The dashboard
  holds one instance and drives it with ``set_transactions(raw_txns)``.
"""

from __future__ import annotations

import asyncio
import datetime as _dt
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, timedelta

import flet as ft

from src.views import tokens
from src.views.transactions_table import (
    _COL_AMOUNT,
    _COL_BALANCE,
    _COL_DESC,
    _COL_TYPE,
    _GUTTER_GAP,
    _GUTTER_WIDTH,
    _ROW_VERT_PAD,
    _amount_cell,
    _build_search_field,
    _column_label,
    _day_gutter,
    _empty_state,
    build_filter_chip,
)

# Render cap. 90 days across every account can run past a thousand rows,
# which Flet renders eagerly; the cap keeps the tab responsive and the
# note below the ledger tells the user how to narrow the list.
_MAX_ROWS = 400

# Flow filter identifiers — internal state values.
_FLOW_ALL = "all"
_FLOW_IN = "in"
_FLOW_OUT = "out"

_FLOW_DEFS: list[tuple[str, str]] = [
    (_FLOW_ALL, "All"),
    (_FLOW_IN, "Money in"),
    (_FLOW_OUT, "Money out"),
]

# Period chips: how far back the ledger reaches, in days. The upstream
# fetch window (DEFAULT_LOOKBACK_DAYS) comfortably covers the longest
# option.
_PERIOD_DEFS: list[tuple[str, str]] = [
    ("7", "7 days"),
    ("30", "30 days"),
    ("90", "90 days"),
]
_DEFAULT_PERIOD = "7"


@dataclass(frozen=True)
class HistoryTransaction:
    """A completed transaction, normalized from the raw Monarch dict."""

    # _dt.date, not bare `date`: the field name shadows the type name in
    # the class namespace (AGENTS.md convention, see alerts.py::Alert.date).
    date: _dt.date
    name: str
    category: str
    account_id: str
    account_name: str
    amount: float


def parse_history_transactions(raw_txns: list[dict]) -> list[HistoryTransaction]:
    """Normalize raw Monarch transaction dicts, newest first.

    Pending transactions are dropped (the ledger shows completed activity
    only), as are rows with unparseable dates or amounts — the same
    defensive posture the recurring detector takes with this feed.
    """
    parsed: list[HistoryTransaction] = []
    for raw in raw_txns:
        if raw.get("pending"):
            continue
        try:
            txn_date = date.fromisoformat(str(raw.get("date", ""))[:10])
        except ValueError:
            continue
        try:
            amount = float(raw.get("amount") or 0.0)
        except (TypeError, ValueError):
            continue
        merchant = (raw.get("merchant") or {}).get("name", "")
        name = merchant or str(raw.get("plaidName") or "") or "(no description)"
        account = raw.get("account") or {}
        parsed.append(
            HistoryTransaction(
                date=txn_date,
                name=name,
                category=(raw.get("category") or {}).get("name", ""),
                account_id=account.get("id", ""),
                account_name=account.get("displayName", ""),
                amount=amount,
            )
        )
    parsed.sort(key=lambda t: t.date, reverse=True)
    return parsed


# ---------------------------------------------------------------------------
# Cell + row builders
# ---------------------------------------------------------------------------


def _category_cell(category: str) -> ft.Control:
    return ft.Text(
        (category or "uncategorized").upper(),
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


def _history_row(txn: HistoryTransaction, *, muted: bool = False) -> ft.Control:
    """One completed-transaction row.

    ``muted`` (the combined Both ledger) mirrors the projected ledger's
    exact column geometry — description, category, amount with the 22px
    pencil slot, and an empty running-balance column — so past and
    projected rows read as one table. The muting is carried by a subtle
    PAPER_2 band and a stepped-down name color; amounts keep their
    signal colors.
    """
    name = ft.Text(
        txn.name,
        style=tokens.body_style(tokens.INK_2 if muted else tokens.INK),
        max_lines=1,
        overflow=ft.TextOverflow.ELLIPSIS,
    )
    cells: list[ft.Control]
    if muted:
        cells = [
            ft.Container(content=name, width=_COL_DESC),
            ft.Container(content=_category_cell(txn.category), width=_COL_TYPE),
            ft.Container(
                content=ft.Row(
                    controls=[_amount_cell(txn.amount), ft.Container(width=22)],
                    spacing=2,
                    tight=True,
                    alignment=ft.MainAxisAlignment.END,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                width=_COL_AMOUNT,
                alignment=ft.Alignment(1, 0),
            ),
            ft.Container(width=_COL_BALANCE),  # no running balance in the past
        ]
    else:
        cells = [
            ft.Container(content=name, width=_COL_DESC),
            ft.Container(content=_category_cell(txn.category), width=_COL_TYPE),
            ft.Container(
                content=_amount_cell(txn.amount),
                width=_COL_AMOUNT,
                alignment=ft.Alignment(1, 0),
            ),
        ]
    return ft.Container(
        content=ft.Row(
            controls=cells,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=0,
        ),
        padding=ft.Padding.symmetric(vertical=_ROW_VERT_PAD),
    )


def _history_header() -> ft.Control:
    return ft.Container(
        content=ft.Row(
            controls=[
                ft.Container(
                    width=_GUTTER_WIDTH + _GUTTER_GAP,
                    content=_column_label("DATE", _GUTTER_WIDTH),
                ),
                _column_label("DESCRIPTION", _COL_DESC),
                _column_label("CATEGORY", _COL_TYPE),
                _column_label("AMOUNT", _COL_AMOUNT, align_right=True),
            ],
            spacing=0,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        padding=ft.Padding.only(bottom=10, top=4),
        border=ft.Border(bottom=ft.BorderSide(1, tokens.RULE)),
    )


def _truncation_note(shown: int) -> ft.Control:
    return ft.Container(
        content=ft.Text(
            f"Showing the {shown} most recent transactions. "
            "Use search or a shorter period to narrow the list.",
            style=tokens.body_style(tokens.INK_3),
        ),
        padding=ft.Padding.symmetric(vertical=16),
        alignment=ft.Alignment(0, 0),
    )


# ---------------------------------------------------------------------------
# Public builder (no filter UI — kept stable for the a11y test)
# ---------------------------------------------------------------------------


def build_recent_transactions_table(
    txns: list[HistoryTransaction],
    *,
    today: date | None = None,
    should_show: Callable[[HistoryTransaction], bool] | None = None,
    empty_headline: str = "No completed transactions to show.",
    empty_hint: str = "Transactions appear here after your accounts sync.",
    max_rows: int = _MAX_ROWS,
    muted: bool = False,
) -> ft.Control:
    """Build the history day-block ledger from normalized transactions.

    ``txns`` is expected newest-first (``parse_history_transactions``
    guarantees this). Days render in that order, each with the shared
    day gutter, so the visual language matches the Upcoming ledger.
    """
    today_d = today or date.today()
    visible = [t for t in txns if should_show is None or should_show(t)]
    truncated = len(visible) > max_rows
    if truncated:
        visible = visible[:max_rows]

    blocks: list[ft.Control] = [] if muted else [_history_header()]
    day_txns: list[HistoryTransaction] = []
    rendered_blocks = 0

    def flush_day() -> None:
        nonlocal rendered_blocks
        if not day_txns:
            return
        net = sum(t.amount for t in day_txns)
        body = ft.Column(
            controls=[_history_row(t, muted=muted) for t in day_txns],
            spacing=0,
            tight=True,
            expand=True,
        )
        blocks.append(
            ft.Container(
                content=ft.Row(
                    controls=[
                        _day_gutter(day_txns[0].date, today_d, net, len(day_txns)),
                        ft.Container(width=_GUTTER_GAP),
                        body,
                    ],
                    spacing=0,
                    vertical_alignment=ft.CrossAxisAlignment.START,
                    expand=True,
                ),
                padding=ft.Padding.only(top=2, bottom=10),
                border=(
                    None if rendered_blocks == 0 else ft.Border(top=ft.BorderSide(1, tokens.RULE))
                ),
            )
        )
        rendered_blocks += 1
        day_txns.clear()

    for txn in visible:
        if day_txns and txn.date != day_txns[0].date:
            flush_day()
        day_txns.append(txn)
    flush_day()

    if rendered_blocks == 0:
        blocks.append(_empty_state(empty_headline, empty_hint))
    elif truncated:
        blocks.append(_truncation_note(max_rows))

    return ft.Column(controls=blocks, spacing=0, tight=True)


# ---------------------------------------------------------------------------
# Stateful view: summary strip + filter strip + ledger
# ---------------------------------------------------------------------------


class RecentTransactionsView(ft.Column):
    """Summary + filter strip + history ledger.

    Owns its own search/filter state so the inputs survive data refreshes
    — the dashboard creates one instance and drives it with
    ``set_transactions(raw_txns)`` whenever a load finishes.
    """

    def __init__(self) -> None:
        super().__init__()
        self._txns: list[HistoryTransaction] = []
        self._search: str = ""
        self._flow: str = _FLOW_ALL
        self._period: str = _DEFAULT_PERIOD
        # The ledger is strictly scoped to the checking account selected in
        # the dashboard dropdown. This app balances one checkbook at a
        # time: mixing accounts made card-side payment credits read as
        # phantom income next to checking outflows.
        self._account_id: str = ""
        # Compact mode (used inside the combined Both ledger): filter strip
        # hidden and rows muted; order stays newest-first so the ledger
        # reads down from the projected section through the today line.
        self._compact = False
        self._rebuild_seq = 0  # Debounce token for search-driven rebuilds.
        self._cutoff_date: date = date.today() - timedelta(days=int(self._period))

        self._search_field = _build_search_field(
            label="Search recent transactions",
            hint_text="Search description, category",
            on_change=self._on_search_change,
            tooltip="Filter recent transactions",
        )

        self._flow_chip_row = ft.Row(spacing=8, wrap=True, run_spacing=8)
        self._period_chip_row = ft.Row(spacing=8, wrap=True, run_spacing=8)
        self._rebuild_chips()

        self._filter_strip = ft.Container(
            content=ft.Row(
                controls=[
                    self._search_field,
                    ft.Container(width=16),
                    self._flow_chip_row,
                    ft.Container(width=16),
                    self._period_chip_row,
                ],
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                wrap=True,
                run_spacing=12,
            ),
            padding=ft.Padding.only(bottom=8),
        )

        self._ledger_container = ft.Container()
        self._rebuild()

        self.spacing = 12
        self.controls = [self._filter_strip, self._ledger_container]

    # ---- Public API -----------------------------------------------------

    def set_transactions(self, raw_txns: list[dict]) -> None:
        self._txns = parse_history_transactions(raw_txns)
        self._rebuild()

    def set_account_filter(self, account_id: str) -> None:
        """Strictly scope the ledger to one account.

        The dashboard calls this with the selected checking account on
        load and on every dropdown change; there is deliberately no
        "all accounts" escape hatch. An empty id (no checking account
        selected yet) shows nothing.
        """
        self._account_id = account_id
        self._rebuild()

    def set_compact(self, compact: bool) -> None:
        """Compact mode for the combined Both ledger: hides the filter
        strip (the combined view owns the framing) and renders rows
        muted, so completed activity reads recessed under the projected
        ledger while staying newest-first."""
        if self._compact == compact:
            return
        self._compact = compact
        self._filter_strip.visible = not compact
        # One continuous tint under the whole ledger — day gutters and the
        # padding between day blocks included — so the past reads as a
        # single recessed surface instead of striped rows.
        self._ledger_container.bgcolor = tokens.PAPER_2 if compact else None
        try:
            self._filter_strip.update()
        except (RuntimeError, AssertionError):
            pass
        self._rebuild()

    def clear(self) -> None:
        """Drop the rendered ledger — used when the dashboard has no data
        to show (fatal load error)."""
        self._txns = []
        self._account_id = ""
        self._rebuild()

    # ---- State handlers -------------------------------------------------

    def _on_search_change(self, e: ft.Event[ft.TextField]) -> None:
        self._search = (e.control.value or "").strip().lower()
        self._schedule_rebuild()

    def _schedule_rebuild(self) -> None:
        """Debounce search-driven rebuilds: reconstructing up to _MAX_ROWS
        rows per keystroke is wasteful. Falls back to an immediate
        synchronous rebuild when unmounted (tests, teardown)."""
        self._rebuild_seq += 1
        seq = self._rebuild_seq
        try:
            page = self.page
        except RuntimeError:
            page = None
        if not isinstance(page, ft.Page):
            self._rebuild()
            return

        async def _later() -> None:
            await asyncio.sleep(0.18)
            if seq == self._rebuild_seq:
                self._rebuild()

        try:
            page.run_task(_later)
        except (AssertionError, RuntimeError):
            self._rebuild()

    def _on_flow_select(self, value: str) -> None:
        if self._flow == value:
            return
        self._flow = value
        self._rebuild_chips()
        self._rebuild()

    def _on_period_select(self, value: str) -> None:
        if self._period == value:
            return
        self._period = value
        self._rebuild_chips()
        self._rebuild()

    def _should_show(self, txn: HistoryTransaction) -> bool:
        if txn.account_id != self._account_id:
            return False
        # _cutoff_date is refreshed once per rebuild, not per row.
        if txn.date < self._cutoff_date:
            return False
        if self._search:
            haystack = f"{txn.name} {txn.category}".lower()
            if self._search not in haystack:
                return False
        if self._flow == _FLOW_IN:
            return txn.amount > 0
        if self._flow == _FLOW_OUT:
            return txn.amount < 0
        return True

    # ---- Rebuilds -------------------------------------------------------

    def _rebuild_chips(self) -> None:
        self._flow_chip_row.controls = [
            build_filter_chip(
                label=label,
                value=value,
                selected=value == self._flow,
                on_select=self._on_flow_select,
            )
            for value, label in _FLOW_DEFS
        ]
        self._period_chip_row.controls = [
            build_filter_chip(
                label=label,
                value=value,
                selected=value == self._period,
                on_select=self._on_period_select,
                sr_prefix="Period",
            )
            for value, label in _PERIOD_DEFS
        ]
        for row in (self._flow_chip_row, self._period_chip_row):
            try:
                row.update()
            except (RuntimeError, AssertionError):
                pass

    def _rebuild(self) -> None:
        self._cutoff_date = date.today() - timedelta(days=int(self._period))
        empty_headline, empty_hint = self._empty_copy()
        self._ledger_container.content = build_recent_transactions_table(
            self._txns,
            should_show=self._should_show,
            empty_headline=empty_headline,
            empty_hint=empty_hint,
            muted=self._compact,
        )
        try:
            self._ledger_container.update()
        except (RuntimeError, AssertionError):
            pass

    def _empty_copy(self) -> tuple[str, str]:
        if not self._txns:
            return (
                "No completed transactions to show.",
                "Transactions appear here after your accounts sync.",
            )
        if self._search:
            return (
                "No transactions match that search.",
                f"Nothing in the selected period matches “{self._search}”.",
            )
        return (
            "No transactions for this account in this period.",
            "Pick a longer period, or clear the filters to see more.",
        )

    # ---- Test/escape hatch ---------------------------------------------

    @property
    def search_field(self) -> ft.TextField:
        """Expose the search field so the dashboard can focus it on tab switch."""
        return self._search_field
