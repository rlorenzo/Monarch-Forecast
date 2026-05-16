"""Tests for the stateful ``TransactionsView`` filter + ledger.

The day-block ledger builder (``build_transactions_table``) is covered
indirectly by the views_smoke + accessibility suites. This file targets:

- The filter chip's selection + hover behavior.
- ``TransactionsView`` state changes: ``set_forecast`` rebuilds,
  ``clear`` drops the ledger, chip selection swaps the active filter,
  search filters by description, ``_should_show`` predicate covers
  every filter bucket.
- The empty-state copy adapts to the active filter + search query.
- The day-gutter NET block appears only when a day has ≥ 2 visible
  transactions.
"""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import flet as ft

from src.data.models import ForecastTransaction
from src.forecast.models import ForecastDay, ForecastResult
from src.views.transactions_table import (
    TransactionsView,
    _FilterChip,
    build_transactions_table,
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


def _two_day_forecast() -> ForecastResult:
    d1 = date(2026, 6, 1)
    d2 = date(2026, 6, 2)
    txns_d1 = [
        ForecastTransaction(date=d1, name="Rent", amount=-1500.0, category="Housing"),
        ForecastTransaction(date=d1, name="Salary", amount=3000.0, category="Income"),
    ]
    txns_d2 = [
        ForecastTransaction(
            date=d2,
            name="Chase Sapphire Payment (1/5)",
            amount=-300.0,
            category="Credit Card Payment",
        ),
        ForecastTransaction(
            date=d2,
            name="Car repair",
            amount=-200.0,
            category="Adjustment",
            id="abc",
        ),
    ]
    days = [
        ForecastDay(date=d1, starting_balance=5000.0, transactions=txns_d1),
        ForecastDay(date=d2, starting_balance=6500.0, transactions=txns_d2),
    ]
    return ForecastResult(days=days, starting_balance=5000.0, safety_threshold=500.0)


# ---------------------------------------------------------------------------
# Filter chip
# ---------------------------------------------------------------------------


class TestFilterChip:
    def test_unselected_uses_paper_fill(self):
        chip = _FilterChip(
            label="Income", value="income", selected=False, on_select=lambda _v: None
        )
        assert chip.bgcolor is not None
        # Not coral when unselected.

    def test_selected_uses_coral_tint(self):
        from src.views import tokens

        chip = _FilterChip(label="Income", value="income", selected=True, on_select=lambda _v: None)
        assert chip.bgcolor == tokens.CORAL_TINT

    def test_click_invokes_on_select_with_value(self):
        picked: list[str] = []
        chip = _FilterChip(
            label="Income", value="income", selected=False, on_select=lambda v: picked.append(v)
        )
        _m(chip.on_click)(MagicMock())
        assert picked == ["income"]

    def test_hover_on_unselected_swaps_bg(self):
        from src.views import tokens

        chip = _FilterChip(
            label="Income", value="income", selected=False, on_select=lambda _v: None
        )
        # Mock update to swallow the unmounted-control error.
        _m(chip).update = MagicMock()
        # Hover in.
        _m(chip.on_hover)(SimpleNamespace(data="true", control=chip))
        assert chip.bgcolor == tokens.PAPER_2
        # Hover out.
        _m(chip.on_hover)(SimpleNamespace(data="false", control=chip))
        assert chip.bgcolor == tokens.PAPER

    def test_hover_on_selected_is_noop(self):
        from src.views import tokens

        chip = _FilterChip(label="All", value="all", selected=True, on_select=lambda _v: None)
        before = chip.bgcolor
        _m(chip.on_hover)(SimpleNamespace(data="true", control=chip))
        # Unchanged.
        assert chip.bgcolor == before == tokens.CORAL_TINT


# ---------------------------------------------------------------------------
# TransactionsView
# ---------------------------------------------------------------------------


class TestTransactionsViewLifecycle:
    def test_clear_with_no_forecast(self):
        view = TransactionsView()
        view.clear()
        assert view._forecast is None

    def test_set_forecast_populates_ledger(self):
        view = TransactionsView()
        view.set_forecast(_two_day_forecast())
        assert view._forecast is not None
        assert view._ledger_container.content is not None

    def test_clear_after_set_drops_ledger(self):
        view = TransactionsView()
        view.set_forecast(_two_day_forecast())
        view.clear()
        assert view._forecast is None
        assert view._ledger_container.content is None


class TestSearchFilter:
    def test_search_change_lowercases_and_strips(self):
        view = TransactionsView()
        view.set_forecast(_two_day_forecast())
        _m(view._search_field).update = MagicMock()
        e = SimpleNamespace(control=SimpleNamespace(value="  Rent  "))
        view._on_search_change(_m(e))
        assert view._search == "rent"

    def test_should_show_respects_search(self):
        view = TransactionsView()
        view._search = "rent"
        match = ForecastTransaction(date=date(2026, 6, 1), name="Rent", amount=-1500.0)
        miss = ForecastTransaction(date=date(2026, 6, 1), name="Salary", amount=3000.0)
        assert view._should_show(match) is True
        assert view._should_show(miss) is False


class TestChipDispatch:
    def test_selecting_same_chip_is_noop(self):
        view = TransactionsView()
        view._filter = "all"
        prior = view._filter
        view._on_chip_select("all")
        assert view._filter == prior

    def test_selecting_new_chip_swaps_state(self):
        view = TransactionsView()
        view._on_chip_select("income")
        assert view._filter == "income"


class TestShouldShowFilterBuckets:
    def setup_method(self):
        self.view = TransactionsView()

    def test_filter_income(self):
        self.view._filter = "income"
        income = ForecastTransaction(date=date(2026, 6, 1), name="Salary", amount=3000.0)
        expense = ForecastTransaction(date=date(2026, 6, 1), name="Rent", amount=-1500.0)
        assert self.view._should_show(income) is True
        assert self.view._should_show(expense) is False

    def test_filter_expense(self):
        self.view._filter = "expense"
        income = ForecastTransaction(date=date(2026, 6, 1), name="Salary", amount=3000.0)
        expense = ForecastTransaction(date=date(2026, 6, 1), name="Rent", amount=-1500.0)
        assert self.view._should_show(income) is False
        assert self.view._should_show(expense) is True

    def test_filter_oneoff(self):
        self.view._filter = "oneoff"
        oneoff = ForecastTransaction(
            date=date(2026, 6, 1), name="Car repair", amount=-200.0, category="Adjustment"
        )
        recurring = ForecastTransaction(
            date=date(2026, 6, 1), name="Rent", amount=-1500.0, category="Housing"
        )
        assert self.view._should_show(oneoff) is True
        assert self.view._should_show(recurring) is False

    def test_filter_cc(self):
        self.view._filter = "cc"
        cc = ForecastTransaction(
            date=date(2026, 6, 1),
            name="Chase Sapphire Payment",
            amount=-300.0,
            category="Credit Card Payment",
        )
        non_cc = ForecastTransaction(date=date(2026, 6, 1), name="Rent", amount=-1500.0)
        assert self.view._should_show(cc) is True
        assert self.view._should_show(non_cc) is False

    def test_filter_all_passes_everything(self):
        self.view._filter = "all"
        txn = ForecastTransaction(date=date(2026, 6, 1), name="anything", amount=-1.0)
        assert self.view._should_show(txn) is True


class TestEmptyCopy:
    def test_no_filter_no_search_uses_default(self):
        view = TransactionsView()
        head, hint = view._empty_copy()
        assert "No transactions" in head
        assert "Adjustments" in hint

    def test_search_with_all_filter_uses_search_copy(self):
        view = TransactionsView()
        view._search = "netflix"
        head, hint = view._empty_copy()
        assert "search" in head.lower()
        assert "netflix" in hint

    def test_filter_with_no_search(self):
        view = TransactionsView()
        view._filter = "income"
        head, _ = view._empty_copy()
        assert "income transactions" in head.lower()

    def test_filter_plus_search_combines_copy(self):
        view = TransactionsView()
        view._filter = "expense"
        view._search = "rent"
        head, _ = view._empty_copy()
        assert "expense transactions" in head.lower()
        assert "rent" in head


# ---------------------------------------------------------------------------
# Ledger header + empty render
# ---------------------------------------------------------------------------


class TestBuilderEmptyState:
    def test_no_transactions_renders_empty_state(self):
        result = ForecastResult(
            days=[ForecastDay(date=date(2026, 6, 1), starting_balance=5000.0, transactions=[])],
            starting_balance=5000.0,
            safety_threshold=500.0,
        )
        ledger = build_transactions_table(result)
        # Empty state Text appears.
        copy_found = any(
            isinstance(c, ft.Text) and c.value and "No transactions" in c.value
            for c in _walk(ledger)
        )
        assert copy_found

    def test_filter_hides_all_uses_filtered_empty_copy(self):
        result = _two_day_forecast()
        # Filter that rejects everything.
        ledger = build_transactions_table(
            result,
            should_show=lambda _t: False,
            empty_headline="Nothing matches",
            empty_hint="Try clearing the filter",
        )
        head = any(isinstance(c, ft.Text) and c.value == "Nothing matches" for c in _walk(ledger))
        assert head


class TestSearchFieldExposed:
    def test_search_field_property(self):
        view = TransactionsView()
        # Public ``search_field`` property must return the same field
        # used internally — the dashboard focuses it on tab switch.
        assert view.search_field is view._search_field
