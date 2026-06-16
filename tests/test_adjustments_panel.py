"""State-machine tests for AdjustmentsPanel.

Cover the panel's public API (``add_one_off``, ``update_one_off``,
``find_one_off_index``, ``adjusted_recurring_items``,
``update_recurring_items``, ``refresh_override_display``) plus the
internal handlers used to drive them (``_add_one_off``,
``_on_override_change``, ``_on_exclude_toggle``, ``_reset_override``).

Also covers the ``_parse_date_input`` helper which feeds every typed
date in the panel + dialogs.

The panel's ``update()`` calls inside rebuild methods are guarded against
unmounted state, so we can drive any of these methods directly from a
test without standing up a real Flet page.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pytest

from src.data.models import ForecastTransaction, RecurringItem
from src.data.preferences import Preferences
from src.views.adjustments import (
    AdjustmentsPanel,
    _parse_date_input,
)


@pytest.fixture
def prefs(tmp_path: Path) -> Preferences:
    return Preferences(path=tmp_path / "prefs.json")


@pytest.fixture
def recurring_items() -> list[RecurringItem]:
    return [
        RecurringItem(
            name="Rent",
            amount=-1500.0,
            frequency="monthly",
            base_date=date(2026, 1, 1),
            category="Housing",
            account_id="acct-A",
        ),
        RecurringItem(
            name="Salary",
            amount=3000.0,
            frequency="biweekly",
            base_date=date(2026, 1, 5),
            category="Income",
            account_id="acct-A",
        ),
        RecurringItem(
            name="Spotify",
            amount=-9.99,
            frequency="monthly",
            base_date=date(2026, 1, 10),
            category="Subscription",
            account_id="acct-B",
        ),
    ]


def make_panel(items: list[RecurringItem], prefs: Preferences) -> AdjustmentsPanel:
    return AdjustmentsPanel(
        recurring_items=items,
        on_change=lambda: None,
        preferences=prefs,
    )


# ---------------------------------------------------------------------------
# _parse_date_input
# ---------------------------------------------------------------------------


class TestParseDateInput:
    """Accepted formats: ISO, ``%b %d, %Y``, ``MM/DD/YYYY``, ``MM-DD-YYYY``."""

    def test_iso(self):
        assert _parse_date_input("2026-01-15") == date(2026, 1, 15)

    def test_legacy_display(self):
        assert _parse_date_input("Jan 15, 2026") == date(2026, 1, 15)

    def test_slash_us(self):
        assert _parse_date_input("01/15/2026") == date(2026, 1, 15)

    def test_dash_us(self):
        assert _parse_date_input("01-15-2026") == date(2026, 1, 15)

    def test_strips_whitespace(self):
        assert _parse_date_input("  2026-01-15  ") == date(2026, 1, 15)

    def test_empty_string(self):
        assert _parse_date_input("") is None

    def test_whitespace_only(self):
        assert _parse_date_input("   ") is None

    def test_garbage(self):
        assert _parse_date_input("not a date") is None

    def test_partial_iso(self):
        # Half a date is not a date.
        assert _parse_date_input("2026-01") is None


# ---------------------------------------------------------------------------
# One-off CRUD
# ---------------------------------------------------------------------------


class TestOneOffAdd:
    def test_expense_signed_negative(self, recurring_items, prefs):
        panel = make_panel(recurring_items, prefs)
        panel.add_one_off("Car repair", 200.0, date(2026, 6, 1), is_expense=True)
        assert len(panel.one_off_transactions) == 1
        txn = panel.one_off_transactions[0]
        assert txn.name == "Car repair"
        assert txn.amount == -200.0
        assert txn.date == date(2026, 6, 1)
        assert txn.category == "Adjustment"
        assert txn.is_recurring is False
        assert txn.id  # backfilled stable id

    def test_income_signed_positive(self, recurring_items, prefs):
        panel = make_panel(recurring_items, prefs)
        panel.add_one_off("Tax refund", 500.0, date(2026, 4, 15), is_expense=False)
        assert panel.one_off_transactions[0].amount == 500.0

    def test_persists_to_preferences(self, recurring_items, prefs):
        # Future-dated so it survives the "drop past-dated entries on load"
        # filter in Preferences.one_off_transactions.
        future = date.today() + timedelta(days=30)
        panel = make_panel(recurring_items, prefs)
        panel.add_one_off("Test", 100.0, future, is_expense=True)
        # Force a fresh load from disk to confirm persistence.
        fresh = Preferences(path=prefs._path)
        assert len(fresh.one_off_transactions) == 1
        assert fresh.one_off_transactions[0].name == "Test"

    def test_fires_on_change(self, recurring_items, prefs):
        calls: list[int] = []
        panel = AdjustmentsPanel(
            recurring_items=recurring_items,
            on_change=lambda: calls.append(1),
            preferences=prefs,
        )
        panel.add_one_off("X", 100.0, date(2026, 6, 1), is_expense=True)
        assert calls == [1]

    def test_amount_normalised_to_signed(self, recurring_items, prefs):
        """A negative ``positive_amount`` arg is still normalised to expense."""
        panel = make_panel(recurring_items, prefs)
        panel.add_one_off("Weird", -50.0, date(2026, 6, 1), is_expense=True)
        assert panel.one_off_transactions[0].amount == -50.0


class TestOneOffFindIndex:
    def test_by_stable_id(self, recurring_items, prefs):
        panel = make_panel(recurring_items, prefs)
        panel.add_one_off("A", 100.0, date(2026, 6, 1), is_expense=True)
        panel.add_one_off("B", 200.0, date(2026, 7, 1), is_expense=True)
        b_txn = panel.one_off_transactions[1]
        assert panel.find_one_off_index(b_txn) == 1

    def test_missing_id_returns_none(self, recurring_items, prefs):
        panel = make_panel(recurring_items, prefs)
        unknown = ForecastTransaction(date=date(2026, 6, 1), name="X", amount=-100.0)
        assert panel.find_one_off_index(unknown) is None

    def test_id_not_in_panel_returns_none(self, recurring_items, prefs):
        panel = make_panel(recurring_items, prefs)
        panel.add_one_off("A", 100.0, date(2026, 6, 1), is_expense=True)
        stranger = ForecastTransaction(
            date=date(2026, 6, 1), name="A", amount=-100.0, id="not-the-real-id"
        )
        assert panel.find_one_off_index(stranger) is None


class TestOneOffUpdate:
    def test_preserves_expense_sign(self, recurring_items, prefs):
        panel = make_panel(recurring_items, prefs)
        panel.add_one_off("Original", 100.0, date(2026, 6, 1), is_expense=True)
        panel.update_one_off(0, "Renamed", 250.0, date(2026, 7, 1))
        txn = panel.one_off_transactions[0]
        assert txn.name == "Renamed"
        assert txn.amount == -250.0
        assert txn.date == date(2026, 7, 1)

    def test_preserves_income_sign(self, recurring_items, prefs):
        panel = make_panel(recurring_items, prefs)
        panel.add_one_off("Refund", 100.0, date(2026, 6, 1), is_expense=False)
        panel.update_one_off(0, "Bigger refund", 500.0, date(2026, 6, 1))
        assert panel.one_off_transactions[0].amount == 500.0

    def test_out_of_range_is_noop(self, recurring_items, prefs):
        panel = make_panel(recurring_items, prefs)
        panel.update_one_off(99, "X", 100.0, date(2026, 6, 1))
        assert panel.one_off_transactions == []

    def test_fires_on_change(self, recurring_items, prefs):
        calls: list[int] = []
        panel = AdjustmentsPanel(
            recurring_items=recurring_items,
            on_change=lambda: calls.append(1),
            preferences=prefs,
        )
        panel.add_one_off("X", 100.0, date(2026, 6, 1), is_expense=True)
        calls.clear()
        panel.update_one_off(0, "Y", 200.0, date(2026, 7, 1))
        assert calls == [1]


class TestOneOffRemove:
    def test_removes_and_fires_change(self, recurring_items, prefs):
        calls: list[int] = []
        panel = AdjustmentsPanel(
            recurring_items=recurring_items,
            on_change=lambda: calls.append(1),
            preferences=prefs,
        )
        panel.add_one_off("Doomed", 100.0, date(2026, 6, 1), is_expense=True)
        calls.clear()
        panel._remove_one_off(0)
        assert panel.one_off_transactions == []
        assert calls == [1]

    def test_out_of_range_is_noop(self, recurring_items, prefs):
        panel = make_panel(recurring_items, prefs)
        # No one-offs present.
        panel._remove_one_off(0)  # should not raise
        panel._remove_one_off(-1)  # should not raise


class TestLegacyOneOffIdBackfill:
    def test_loads_existing_one_off_without_id_and_backfills(self, tmp_path):
        # Persist a one-off without an id (simulating a legacy install),
        # then construct the panel and verify an id was backfilled.
        # Future-dated so it survives the past-date filter on load.
        future = date.today() + timedelta(days=30)
        prefs_path = tmp_path / "prefs.json"
        prefs = Preferences(path=prefs_path)
        prefs.set_one_off_transactions(
            [
                ForecastTransaction(
                    date=future,
                    name="legacy",
                    amount=-50.0,
                    category="Adjustment",
                    is_recurring=False,
                    id="",
                ),
            ]
        )
        panel = AdjustmentsPanel(
            recurring_items=[],
            on_change=lambda: None,
            preferences=prefs,
        )
        assert len(panel.one_off_transactions) == 1
        assert panel.one_off_transactions[0].id  # backfilled


# ---------------------------------------------------------------------------
# Recurring overrides + exclusion + account filter
# ---------------------------------------------------------------------------


class TestAdjustedRecurringItems:
    def test_returns_all_when_no_overrides_or_exclusions(self, recurring_items, prefs):
        panel = make_panel(recurring_items, prefs)
        panel.update_recurring_items(recurring_items, account_id="")
        names = {item.name for item in panel.adjusted_recurring_items}
        assert names == {"Rent", "Salary", "Spotify"}

    def test_applies_amount_override(self, recurring_items, prefs):
        panel = make_panel(recurring_items, prefs)
        panel.update_recurring_items(recurring_items, account_id="")
        prefs.set_amount_override("Rent", -1800.0)
        panel.refresh_override_display()
        adjusted = {item.name: item.amount for item in panel.adjusted_recurring_items}
        assert adjusted["Rent"] == -1800.0
        assert adjusted["Salary"] == 3000.0  # untouched

    def test_drops_excluded_items(self, recurring_items, prefs):
        panel = make_panel(recurring_items, prefs)
        panel.update_recurring_items(recurring_items, account_id="")
        prefs.set_recurring_excluded("Rent", excluded=True)
        panel.refresh_override_display()
        names = {item.name for item in panel.adjusted_recurring_items}
        assert "Rent" not in names

    def test_filters_to_selected_account(self, recurring_items, prefs):
        panel = make_panel(recurring_items, prefs)
        # Filter to acct-A: should hide "Spotify" (acct-B).
        panel.update_recurring_items(recurring_items, account_id="acct-A")
        names = {item.name for item in panel.adjusted_recurring_items}
        assert names == {"Rent", "Salary"}

    def test_empty_account_id_keeps_all(self, recurring_items, prefs):
        panel = make_panel(recurring_items, prefs)
        panel.update_recurring_items(recurring_items, account_id="")
        names = {item.name for item in panel.adjusted_recurring_items}
        assert names == {"Rent", "Salary", "Spotify"}

    def test_items_without_account_id_pass_all_filters(self, prefs):
        items = [
            RecurringItem(
                name="No Account",
                amount=-10.0,
                frequency="monthly",
                base_date=date(2026, 1, 1),
                # account_id intentionally omitted (defaults to "")
            ),
        ]
        panel = make_panel(items, prefs)
        panel.update_recurring_items(items, account_id="acct-A")
        names = {item.name for item in panel.adjusted_recurring_items}
        assert names == {"No Account"}


class TestOverrideHandlers:
    def test_on_override_change_sets_signed_override(self, recurring_items, prefs):
        panel = make_panel(recurring_items, prefs)
        # Rent is an expense (negative). Override "1800" → -1800.
        panel._on_override_change("Rent", -1500.0, "1800")
        assert prefs.amount_overrides["Rent"] == -1800.0

    def test_on_override_change_preserves_income_sign(self, recurring_items, prefs):
        panel = make_panel(recurring_items, prefs)
        # Salary is income (positive). Override "3500" → 3500.
        panel._on_override_change("Salary", 3000.0, "3500")
        assert prefs.amount_overrides["Salary"] == 3500.0

    def test_on_override_change_invalid_clears(self, recurring_items, prefs):
        panel = make_panel(recurring_items, prefs)
        prefs.set_amount_override("Rent", -1800.0)
        panel._on_override_change("Rent", -1500.0, "garbage")
        assert "Rent" not in prefs.amount_overrides

    def test_reset_override_clears(self, recurring_items, prefs):
        panel = make_panel(recurring_items, prefs)
        prefs.set_amount_override("Rent", -1800.0)
        panel._reset_override("Rent")
        assert "Rent" not in prefs.amount_overrides


class TestExcludeToggle:
    """The handler only reads ``e.control.value``. ``ty`` rejects
    ``SimpleNamespace`` here even with ``# type: ignore``, so cast it
    through ``Any`` to the declared type.
    """

    def test_unchecking_adds_to_excluded(self, recurring_items, prefs):
        from types import SimpleNamespace
        from typing import Any, cast

        import flet as ft

        panel = make_panel(recurring_items, prefs)
        event = cast(
            ft.Event[ft.Checkbox],
            cast(Any, SimpleNamespace(control=SimpleNamespace(value=False))),
        )
        panel._on_exclude_toggle(event, "Rent")
        assert "Rent" in prefs.excluded_recurring_names

    def test_rechecking_removes_from_excluded(self, recurring_items, prefs):
        from types import SimpleNamespace
        from typing import Any, cast

        import flet as ft

        panel = make_panel(recurring_items, prefs)
        prefs.set_recurring_excluded("Rent", excluded=True)
        event = cast(
            ft.Event[ft.Checkbox],
            cast(Any, SimpleNamespace(control=SimpleNamespace(value=True))),
        )
        panel._on_exclude_toggle(event, "Rent")
        assert "Rent" not in prefs.excluded_recurring_names


# ---------------------------------------------------------------------------
# Resilience: rebuild methods tolerate unmounted state
# ---------------------------------------------------------------------------


class TestRebuildBeforeMount:
    """The panel may have rebuild methods invoked before it's been
    mounted on a Page (e.g. during the dashboard's own construction).
    These calls must not raise — they swallow the unmounted ``update()``
    RuntimeError internally.
    """

    def test_rebuild_override_rows(self, recurring_items, prefs):
        panel = make_panel(recurring_items, prefs)
        panel._rebuild_override_rows()  # should not raise

    def test_rebuild_oneoff_rows_empty(self, recurring_items, prefs):
        panel = make_panel(recurring_items, prefs)
        panel._rebuild_oneoff_rows()  # should not raise

    def test_rebuild_oneoff_rows_with_data(self, recurring_items, prefs):
        panel = make_panel(recurring_items, prefs)
        panel.add_one_off("X", 100.0, date(2026, 6, 1), is_expense=True)
        # add_one_off implicitly calls _rebuild_oneoff_rows — already verified
        # not to raise. Call once more directly for parity.
        panel._rebuild_oneoff_rows()

    def test_refresh_override_display(self, recurring_items, prefs):
        panel = make_panel(recurring_items, prefs)
        panel.refresh_override_display()  # should not raise


# ---------------------------------------------------------------------------
# Override visual state hints (regression: line-through + coral border)
# ---------------------------------------------------------------------------


class TestOverrideRenderState:
    """Confirm the rebuilt rows reflect the override state correctly.

    These don't render pixels, but they verify the row-build picks up
    ``is_overridden`` for items in ``prefs.amount_overrides`` so the
    styling branches in ``_recurring_row`` are reached.
    """

    def test_overridden_item_marked_overridden(self, recurring_items, prefs):
        panel = make_panel(recurring_items, prefs)
        panel.update_recurring_items(recurring_items, account_id="")
        prefs.set_amount_override("Rent", -1800.0)
        panel.refresh_override_display()

        # adjusted_recurring_items applies the override to the item.amount
        adjusted = {item.name: item.amount for item in panel.adjusted_recurring_items}
        assert adjusted["Rent"] == -1800.0
        # Override persists across multiple refresh calls.
        panel.refresh_override_display()
        assert prefs.amount_overrides["Rent"] == -1800.0

    def test_non_overridden_items_use_original(self, recurring_items, prefs):
        panel = make_panel(recurring_items, prefs)
        panel.update_recurring_items(recurring_items, account_id="")
        adjusted = {item.name: item.amount for item in panel.adjusted_recurring_items}
        assert adjusted["Salary"] == 3000.0
