"""Tests for the Recent (completed history) ledger.

Covers:

- ``parse_history_transactions``: pending/bad-row filtering, merchant
  fallback, newest-first ordering.
- ``build_recent_transactions_table``: day grouping, empty state,
  truncation note, display order.
- ``RecentTransactionsView`` state: summary totals, flow/period/search
  filters, ``clear``, empty-state copy.
- Dashboard integration: the Upcoming/Recent mode toggle swaps the tab
  body, hides the Add-One-Off button, and routes tab-entry focus.
"""

from __future__ import annotations

from datetime import date, timedelta
from types import SimpleNamespace
from typing import Any

import flet as ft

from src.views.recent_transactions import (
    HistoryTransaction,
    RecentTransactionsView,
    build_recent_transactions_table,
    parse_history_transactions,
)


def _m(obj: Any) -> Any:
    return obj


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


def _texts(control: Any) -> list[str]:
    return [c.value for c in _walk(control) if isinstance(c, ft.Text) and c.value]


def _sort_toggles(control: Any) -> list[Any]:
    """Every DATE-header sort control in a rendered tree."""
    return [
        c
        for c in _walk(control)
        if isinstance(c, ft.Semantics) and (c.label or "").startswith("Sort by date")
    ]


def _forecast_with_one_day() -> Any:
    """Minimal forecast — enough for the ledger to render its header."""
    from src.data.models import ForecastTransaction
    from src.forecast.models import ForecastDay, ForecastResult

    day = date.today()
    return ForecastResult(
        days=[
            ForecastDay(
                date=day,
                starting_balance=1000.0,
                transactions=[ForecastTransaction(date=day, name="Rent", amount=-500.0)],
            )
        ],
        starting_balance=1000.0,
        safety_threshold=100.0,
    )


def _raw(
    day: date,
    amount: float,
    merchant: str = "Coffee Shop",
    *,
    pending: bool = False,
    category: str = "Food",
    account: str = "Everyday Checking",
) -> dict:
    return {
        "date": day.isoformat(),
        "amount": amount,
        "pending": pending,
        "merchant": {"name": merchant},
        "category": {"name": category},
        "account": {"id": "acct-1", "displayName": account},
    }


class TestParseHistoryTransactions:
    def test_skips_pending_and_bad_rows(self):
        today = date.today()
        raws = [
            _raw(today, -5.0),
            _raw(today, -10.0, pending=True),
            {"date": "not-a-date", "amount": -1.0, "merchant": {"name": "X"}},
            {"date": today.isoformat(), "amount": "garbage", "merchant": {"name": "Y"}},
        ]
        parsed = parse_history_transactions(raws)
        assert len(parsed) == 1
        assert parsed[0].amount == -5.0

    def test_merchant_fallbacks(self):
        today = date.today()
        no_merchant = {
            "date": today.isoformat(),
            "amount": -3.0,
            "merchant": None,
            "plaidName": "ACH DEBIT WATER",
        }
        nothing = {"date": today.isoformat(), "amount": -3.0}
        parsed = parse_history_transactions([no_merchant, nothing])
        assert parsed[0].name == "ACH DEBIT WATER"
        assert parsed[1].name == "(no description)"

    def test_sorted_newest_first(self):
        today = date.today()
        raws = [
            _raw(today - timedelta(days=5), -1.0),
            _raw(today, -2.0),
            _raw(today - timedelta(days=2), -3.0),
        ]
        parsed = parse_history_transactions(raws)
        assert [t.amount for t in parsed] == [-2.0, -3.0, -1.0]

    def test_null_amount_coerces_to_zero(self):
        today = date.today()
        parsed = parse_history_transactions(
            [{"date": today.isoformat(), "amount": None, "merchant": {"name": "Z"}}]
        )
        assert parsed[0].amount == 0.0


class TestBuildRecentTransactionsTable:
    def _txn(self, day: date, amount: float, name: str = "Coffee") -> HistoryTransaction:
        return HistoryTransaction(
            date=day,
            name=name,
            category="Food",
            account_id="acct-1",
            account_name="Checking",
            amount=amount,
        )

    def test_groups_by_day(self):
        d = date(2026, 6, 15)
        txns = [
            self._txn(d, -5.0),
            self._txn(d, -7.0),
            self._txn(d - timedelta(days=1), -9.0),
        ]
        table = build_recent_transactions_table(txns, today=d)
        texts = _texts(table)
        # Two day gutters: Jun 15 and Jun 14.
        assert "JUN 15" in texts
        assert "JUN 14" in texts

    def _day_labels(self, table: Any) -> list[str]:
        """Day-gutter labels in render order (e.g. ``["JUN 14", "JUN 15"]``)."""
        return [t for t in _texts(table) if t.startswith("JUN ")]

    def test_defaults_to_oldest_first(self):
        d = date(2026, 6, 15)
        txns = [self._txn(d, -5.0), self._txn(d - timedelta(days=1), -9.0)]
        assert self._day_labels(build_recent_transactions_table(txns, today=d)) == [
            "JUN 14",
            "JUN 15",
        ]

    def test_newest_first_reverses_days(self):
        d = date(2026, 6, 15)
        txns = [self._txn(d, -5.0), self._txn(d - timedelta(days=1), -9.0)]
        table = build_recent_transactions_table(txns, today=d, newest_first=True)
        assert self._day_labels(table) == ["JUN 15", "JUN 14"]

    def test_oldest_first_still_truncates_to_most_recent(self):
        # Truncation runs before the display flip, so oldest-first shows
        # the most recent max_rows re-ordered — not the oldest rows.
        d = date(2026, 6, 15)
        txns = [self._txn(d - timedelta(days=i), -1.0) for i in range(6)]
        table = build_recent_transactions_table(txns, today=d, max_rows=2, newest_first=False)
        assert self._day_labels(table) == ["JUN 14", "JUN 15"]

    def _note_position(self, table: Any) -> int:
        texts = _texts(table)
        note = next(i for i, t in enumerate(texts) if t.startswith("Showing the "))
        first_day = next(i for i, t in enumerate(texts) if t.startswith("JUN "))
        return note - first_day

    def test_truncation_note_follows_the_dropped_rows(self):
        # The dropped rows are always the oldest, so the note has to sit on
        # whichever end of the ledger they were cut from — below the days
        # newest-first, above them oldest-first. A note pinned to the bottom
        # would point at the newest day and claim rows are missing there.
        d = date(2026, 6, 15)
        txns = [self._txn(d - timedelta(days=i), -1.0) for i in range(6)]
        newest = build_recent_transactions_table(txns, today=d, max_rows=2, newest_first=True)
        oldest = build_recent_transactions_table(txns, today=d, max_rows=2, newest_first=False)
        assert self._note_position(newest) > 0
        assert self._note_position(oldest) < 0

    def test_truncation_note_stays_below_the_header_oldest_first(self):
        d = date(2026, 6, 15)
        txns = [self._txn(d - timedelta(days=i), -1.0) for i in range(6)]
        table = build_recent_transactions_table(
            txns, today=d, max_rows=2, newest_first=False, on_toggle_order=lambda: None
        )
        texts = _texts(table)
        assert texts.index("DATE ↑") < next(
            i for i, t in enumerate(texts) if t.startswith("Showing the ")
        )

    def test_empty_state(self):
        table = build_recent_transactions_table([], today=date(2026, 6, 15))
        assert "No completed transactions to show." in _texts(table)

    def test_truncation_note(self):
        d = date(2026, 6, 15)
        txns = [self._txn(d - timedelta(days=i % 30), -1.0) for i in range(10)]
        table = build_recent_transactions_table(txns, today=d, max_rows=4)
        assert any("4 most recent transactions" in t for t in _texts(table))

    def test_no_unlabeled_icon_buttons(self):
        d = date(2026, 6, 15)
        table = build_recent_transactions_table([self._txn(d, -5.0)], today=d)
        assert not [c for c in _walk(table) if isinstance(c, ft.IconButton)]


class TestRecentTransactionsView:
    def _view_with_data(self) -> RecentTransactionsView:
        today = date.today()
        view = RecentTransactionsView()
        view.set_transactions(
            [
                _raw(today, -50.0, "Grocery Store"),
                _raw(today - timedelta(days=1), 2000.0, "Paycheck", category="Income"),
                _raw(today - timedelta(days=10), -30.0, "Mid Utility", category="Utilities"),
                _raw(today - timedelta(days=40), -80.0, "Old Utility", category="Utilities"),
                _raw(today, -10.0, "Pending Cafe", pending=True),
            ]
        )
        view.set_account_filter("acct-1")
        return view

    def test_default_period_is_seven_days(self):
        view = self._view_with_data()
        shown = [t.name for t in view._txns if view._should_show(t)]
        # 10- and 40-day-old rows are outside the 7-day default window;
        # the pending one was dropped at parse time.
        assert shown == ["Grocery Store", "Paycheck"]

    def test_period_widens_window(self):
        view = self._view_with_data()
        view._on_period_select("30")
        shown = [t.name for t in view._txns if view._should_show(t)]
        assert "Mid Utility" in shown
        assert "Old Utility" not in shown
        view._on_period_select("90")
        shown = [t.name for t in view._txns if view._should_show(t)]
        assert "Old Utility" in shown

    def test_no_summary_strip(self):
        # No money in/out/net strip: the ledger itself is the answer.
        view = self._view_with_data()
        assert "MONEY IN" not in _texts(view)
        assert "MONEY OUT" not in _texts(view)

    def test_flow_filter(self):
        view = self._view_with_data()
        view._on_flow_select("in")
        shown = [t for t in view._txns if view._should_show(t)]
        assert [t.name for t in shown] == ["Paycheck"]

    def test_search_matches_name_and_category(self):
        view = self._view_with_data()
        view._on_search_change(_m(SimpleNamespace(control=SimpleNamespace(value="income"))))
        shown = [t for t in view._txns if view._should_show(t)]
        assert [t.name for t in shown] == ["Paycheck"]
        # Account names are not searchable: the view is single-account
        # by design, so the name would match every row or none.
        view._on_search_change(_m(SimpleNamespace(control=SimpleNamespace(value="everyday"))))
        shown = [t for t in view._txns if view._should_show(t)]
        assert shown == []

    def test_clear_shows_empty_state(self):
        view = self._view_with_data()
        view.clear()
        assert "No completed transactions to show." in _texts(view)

    def test_filtered_out_shows_period_hint(self):
        view = self._view_with_data()
        view._on_flow_select("in")
        view._on_search_change(_m(SimpleNamespace(control=SimpleNamespace(value="zzz"))))
        assert "No transactions match that search." in _texts(view)

    def test_search_field_exposed(self):
        view = RecentTransactionsView()
        assert isinstance(view.search_field, ft.TextField)

    def test_compact_hides_filters_and_mutes_rows(self):
        from src.views import tokens

        view = self._view_with_data()
        view.set_compact(True)
        assert view._filter_strip.visible is False
        # Muting is carried by a subtle PAPER_2 band and a stepped-down
        # name color; amounts KEEP their signal colors, and the duplicate
        # column header disappears (the combined table owns the header).
        name_colors = {
            c.style.color
            for c in _walk(view)
            if isinstance(c, ft.Text) and c.value in ("Grocery Store", "Paycheck")
        }
        assert name_colors == {tokens.INK_2}
        amount_colors = {
            c.style.color
            for c in _walk(view)
            if isinstance(c, ft.Text) and c.value and c.value.startswith(("+ $", "− $"))
        }
        assert tokens.SIGNAL_POSITIVE in amount_colors
        assert tokens.SIGNAL_NEGATIVE in amount_colors
        # The tint is one continuous surface under the whole ledger
        # (gutter and inter-day gaps included), not per-row stripes.
        assert view._ledger_container.bgcolor == tokens.PAPER_2
        assert "DESCRIPTION" not in _texts(view)
        view.set_compact(False)
        assert view._filter_strip.visible is True
        assert view._ledger_container.bgcolor is None
        assert "DESCRIPTION" in _texts(view)

    def test_set_newest_first_reverses_days_and_no_ops_when_unchanged(self):
        view = self._view_with_data()
        before = view._ledger_container.content
        view.set_newest_first(False)
        assert view._ledger_container.content is before
        # Default (oldest first) reads up to today; flipping reverses it.
        names = [t for t in _texts(view) if t in ("Grocery Store", "Paycheck")]
        assert names == ["Paycheck", "Grocery Store"]
        view.set_newest_first(True)
        assert [t for t in _texts(view) if t in ("Grocery Store", "Paycheck")] == [
            "Grocery Store",
            "Paycheck",
        ]


class TestDashboardTxnModeToggle:
    def _dashboard(self, patched_session_manager):
        from src.views.dashboard import DashboardView

        return DashboardView(patched_session_manager, on_logout=lambda: None)

    def test_toggle_swaps_body_and_button(self, patched_session_manager):
        dash = self._dashboard(patched_session_manager)
        assert dash._txn_tab_body.content is dash.transactions_view
        assert dash._add_one_off_button.visible is not False

        dash._on_txn_mode_select("recent")
        assert dash._txn_tab_body.content is dash.recent_transactions_view
        assert dash._add_one_off_button.visible is False
        assert dash._txn_tab_title.value == "Recent"

        dash._on_txn_mode_select("upcoming")
        assert dash._txn_tab_body.content is dash.transactions_view
        assert dash._add_one_off_button.visible is True
        assert dash._txn_tab_title.value == "Upcoming"

    def test_focus_target_follows_mode(self, patched_session_manager, monkeypatch):
        dash = self._dashboard(patched_session_manager)
        focused: list[Any] = []
        monkeypatch.setattr(
            dash, "_run_task", lambda coro_fn, *args: focused.append(args[0] if args else None)
        )
        dash._focus_tab_entry(1)
        assert focused[-1] is dash.transactions_view.search_field
        dash._on_txn_mode_select("recent")
        dash._focus_tab_entry(1)
        assert focused[-1] is dash.recent_transactions_view.search_field


class TestStrictAccountScoping:
    """The ledger is strictly the selected checking account's transactions.
    No account chips, no all-accounts mode: this app balances one
    checkbook at a time."""

    def _view_two_accounts(self) -> RecentTransactionsView:
        today = date.today()
        view = RecentTransactionsView()
        checking = _raw(today, -120.0, "Grocery Store")
        payment_on_card = {
            "date": today.isoformat(),
            "amount": 2853.25,  # payment credit ON the card account
            "merchant": {"name": "Chase Sapphire Reserve"},
            "category": {"name": "Payment"},
            "account": {"id": "cc-1", "displayName": "Chase Sapphire Reserve"},
        }
        view.set_transactions([checking, payment_on_card])
        return view

    def test_scoping_to_checking_hides_card_payment_credit(self):
        view = self._view_two_accounts()
        view.set_account_filter("acct-1")
        shown = [t for t in view._txns if view._should_show(t)]
        assert [t.name for t in shown] == ["Grocery Store"]
        assert "+ $2,853.25" not in _texts(view)
        assert "− $120.00" in _texts(view)

    def test_no_selection_shows_nothing(self):
        view = self._view_two_accounts()
        shown = [t for t in view._txns if view._should_show(t)]
        assert shown == []

    def test_unknown_account_shows_nothing(self):
        # Strict: no silent widening to other accounts.
        view = self._view_two_accounts()
        view.set_account_filter("does-not-exist")
        shown = [t for t in view._txns if view._should_show(t)]
        assert shown == []
        assert "No transactions for this account in this period." in _texts(view)

    def test_scope_survives_data_refresh(self):
        today = date.today()
        view = self._view_two_accounts()
        view.set_account_filter("acct-1")
        view.set_transactions([_raw(today, -60.0, "Coffee")])
        assert view._account_id == "acct-1"
        shown = [t for t in view._txns if view._should_show(t)]
        assert [t.name for t in shown] == ["Coffee"]

    def test_clear_resets_scope(self):
        view = self._view_two_accounts()
        view.set_account_filter("acct-1")
        view.clear()
        assert view._account_id == ""


class TestBothMode:
    def _dashboard(self, patched_session_manager):
        from src.views.dashboard import DashboardView

        return DashboardView(patched_session_manager, on_logout=lambda: None)

    def test_both_mode_combines_ledgers(self, patched_session_manager):
        dash = self._dashboard(patched_session_manager)
        dash._on_txn_mode_select("both")
        assert dash._txn_tab_title.value == "Ledger"
        # The add-one-off button stays: the projected ledger is visible.
        assert dash._add_one_off_button.visible is True
        assert dash.recent_transactions_view._compact is True
        body = dash._txn_tab_body.content
        # Default order is oldest-first, so the completed past leads, the
        # TODAY break follows, and the projection lands last. One hoisted
        # column header sits above both sections.
        assert body.controls[1] is dash.recent_transactions_view
        assert body.controls[-1] is dash.transactions_view
        assert "TODAY" in _texts(body.controls[2])
        assert "BALANCE" in _texts(body.controls[0])
        # The projected view drops its own header so only the hoisted one
        # renders — otherwise a second header lands mid-timeline.
        assert dash.transactions_view._show_header is False

    def test_both_mode_newest_first_puts_projection_on_top(self, patched_session_manager):
        dash = self._dashboard(patched_session_manager)
        dash._on_txn_mode_select("both")
        dash._toggle_txn_order()
        body = dash._txn_tab_body.content
        assert body.controls[1] is dash.transactions_view
        assert body.controls[-1] is dash.recent_transactions_view
        assert "TODAY" in _texts(body.controls[2])

    def test_leaving_both_restores_projected_header(self, patched_session_manager):
        dash = self._dashboard(patched_session_manager)
        dash._on_txn_mode_select("both")
        dash._on_txn_mode_select("upcoming")
        assert dash.transactions_view._show_header is True

    def test_leaving_both_restores_full_recent(self, patched_session_manager):
        dash = self._dashboard(patched_session_manager)
        dash._on_txn_mode_select("both")
        dash._on_txn_mode_select("recent")
        assert dash.recent_transactions_view._compact is False
        assert dash._txn_tab_body.content is dash.recent_transactions_view

    def test_cycle_covers_all_modes(self, patched_session_manager, monkeypatch):
        dash = self._dashboard(patched_session_manager)
        monkeypatch.setattr(dash, "_focus_tab_entry", lambda i: None)
        # Already on the Transactions tab: the toggle only cycles when no
        # tab switch is needed (a blocked switch must not rotate the mode).
        dash._current_nav_index = 1
        seen = [dash._txn_mode]
        for _ in range(3):
            dash.toggle_txn_mode()
            seen.append(dash._txn_mode)
        assert seen == ["upcoming", "recent", "both", "upcoming"]


class TestSortOrder:
    def _dashboard(self, patched_session_manager):
        from src.views.dashboard import DashboardView

        return DashboardView(patched_session_manager, on_logout=lambda: None)

    def test_defaults_to_oldest_first_everywhere(self, patched_session_manager):
        dash = self._dashboard(patched_session_manager)
        assert dash._newest_first is False
        assert dash.transactions_view._newest_first is False
        assert dash.recent_transactions_view._newest_first is False
        assert "oldest first" in dash._txn_tab_subtitle.value

    def test_flip_propagates_to_both_views_and_persists(self, patched_session_manager):
        dash = self._dashboard(patched_session_manager)
        dash._toggle_txn_order()
        assert dash.transactions_view._newest_first is True
        assert dash.recent_transactions_view._newest_first is True
        assert dash._prefs.transactions_newest_first is True
        assert "newest first" in dash._txn_tab_subtitle.value

    def test_saved_order_is_restored_on_construction(self, patched_session_manager):
        dash = self._dashboard(patched_session_manager)
        dash._toggle_txn_order()
        # Same tmp-scoped Preferences file (see conftest), so a fresh
        # dashboard must come up newest-first with no further interaction.
        restored = self._dashboard(patched_session_manager)
        assert restored._newest_first is True
        assert restored.transactions_view._newest_first is True
        assert restored.recent_transactions_view._newest_first is True

    def test_subtitle_tracks_mode_and_order(self, patched_session_manager):
        dash = self._dashboard(patched_session_manager)
        dash._on_txn_mode_select("recent")
        assert dash._txn_tab_subtitle.value.endswith("oldest first.")
        dash._toggle_txn_order()
        assert dash._txn_tab_subtitle.value.endswith("newest first.")

    def test_toggling_twice_returns_to_oldest_first(self, patched_session_manager):
        dash = self._dashboard(patched_session_manager)
        dash._toggle_txn_order()
        dash._toggle_txn_order()
        assert dash._newest_first is False
        assert dash._prefs.transactions_newest_first is False
        assert dash.transactions_view._newest_first is False
        assert dash.recent_transactions_view._newest_first is False

    def test_header_carries_the_control_in_every_mode(self, patched_session_manager):
        # The sort control has no row of its own — it must be reachable
        # from the header of whichever ledger the mode puts on screen.
        dash = self._dashboard(patched_session_manager)
        dash.transactions_view.set_forecast(_forecast_with_one_day())
        dash.recent_transactions_view.set_transactions([])

        for mode in ("upcoming", "recent", "both"):
            dash._on_txn_mode_select(mode)
            toggles = _sort_toggles(dash._txn_tab_body.content)
            assert len(toggles) == 1, f"{mode} should expose exactly one sort control"
            assert "Sort by date" in toggles[0].label

    def test_clicking_the_header_flips_the_order(self, patched_session_manager):
        dash = self._dashboard(patched_session_manager)
        dash.transactions_view.set_forecast(_forecast_with_one_day())
        toggle = _sort_toggles(dash._txn_tab_body.content)[0]
        _m(toggle.content.on_click)(SimpleNamespace(control=toggle.content))
        assert dash._newest_first is True
        # The header re-renders with the flipped state, so the next click
        # advertises the way back rather than repeating itself.
        after = _sort_toggles(dash._txn_tab_body.content)[0]
        assert "currently newest first" in after.label


class TestToggleGuard:
    def test_mode_does_not_rotate_when_tab_switch_is_blocked(
        self, patched_session_manager, monkeypatch
    ):
        from src.views.dashboard import DashboardView

        dash = DashboardView(patched_session_manager, on_logout=lambda: None)
        assert dash._current_nav_index == 0  # Overview
        dash._dirty_cc_cards = {"cc1": {"name": "Card"}}
        monkeypatch.setattr(dash, "_show_unsaved_cc_dialog", lambda: None)
        before = dash._txn_mode
        dash.toggle_txn_mode()
        # switch_to_tab deferred behind the unsaved-changes dialog: the
        # sub-mode must not rotate behind the user's back.
        assert dash._txn_mode == before
        assert dash._current_nav_index == 0
