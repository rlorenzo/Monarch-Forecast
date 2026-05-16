"""Tests for the inline one-off form submit handler on AdjustmentsPanel.

``_add_one_off`` is invoked when the user clicks the coral "+ Add"
button at the top of the Adjustments tab's one-off section. Covers
the four validation paths and the successful add (which also resets
the form for the next entry).

Also covers the editorial button hover handlers (``coral_button``,
``ghost_button``, ``ink_button``) — small bits of UI behavior that
the existing test suites don't reach.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, PropertyMock, patch

import flet as ft
import pytest

from src.data.preferences import Preferences
from src.views import tokens
from src.views.adjustments import (
    AdjustmentsPanel,
    coral_button,
    ghost_button,
    ink_button,
)


def _m(obj: Any) -> Any:
    return obj


@pytest.fixture
def panel(tmp_path: Path):
    """An AdjustmentsPanel with controls' ``.update()`` stubbed and
    ``self.page`` patched on ``BaseControl`` so ``_schedule_focus``
    doesn't trip the unmounted-control guard.
    """
    prefs = Preferences(path=tmp_path / "prefs.json")
    panel = AdjustmentsPanel(recurring_items=[], on_change=lambda: None, preferences=prefs)
    for ctrl_name in (
        "_oneoff_name",
        "_oneoff_amount",
        "_oneoff_error",
        "_oneoff_date_display",
    ):
        _m(getattr(panel, ctrl_name)).update = MagicMock()
    fake_page = MagicMock(spec=ft.Page)
    fake_page.run_task = MagicMock()
    with patch.object(ft.BaseControl, "page", new_callable=PropertyMock, return_value=fake_page):
        yield panel


# ---------------------------------------------------------------------------
# Inline form _add_one_off
# ---------------------------------------------------------------------------


class TestAddOneOffFormValidation:
    def test_empty_name_sets_error(self, panel):
        panel._oneoff_name.value = ""
        panel._oneoff_amount.value = "100"
        panel._add_one_off(MagicMock())
        assert panel._oneoff_error.value == "Description is required."
        assert panel.one_off_transactions == []

    def test_empty_amount_sets_error(self, panel):
        panel._oneoff_name.value = "Car repair"
        panel._oneoff_amount.value = ""
        panel._add_one_off(MagicMock())
        assert panel._oneoff_error.value == "Amount is required."
        assert panel.one_off_transactions == []

    def test_non_numeric_amount_sets_error(self, panel):
        panel._oneoff_name.value = "Car repair"
        panel._oneoff_amount.value = "abc"
        panel._add_one_off(MagicMock())
        assert panel._oneoff_error.value == "Invalid amount."
        assert panel.one_off_transactions == []

    def test_zero_amount_rejected(self, panel):
        panel._oneoff_name.value = "Car repair"
        panel._oneoff_amount.value = "0"
        panel._add_one_off(MagicMock())
        assert panel._oneoff_error.value == "Amount must be greater than 0."
        assert panel.one_off_transactions == []

    def test_negative_amount_rejected(self, panel):
        panel._oneoff_name.value = "Car repair"
        panel._oneoff_amount.value = "-50"
        panel._add_one_off(MagicMock())
        assert panel._oneoff_error.value == "Amount must be greater than 0."
        assert panel.one_off_transactions == []

    def test_amount_with_dollar_sign_and_comma_normalised(self, panel):
        panel._oneoff_name.value = "Car repair"
        panel._oneoff_amount.value = "$1,234.56"
        panel._oneoff_date_display.value = "2026-08-01"
        panel._oneoff_type.value = "expense"
        panel._add_one_off(MagicMock())
        assert len(panel.one_off_transactions) == 1
        assert panel.one_off_transactions[0].amount == -1234.56


class TestAddOneOffFormSuccess:
    def test_adds_expense_and_resets_form(self, panel):
        panel._oneoff_name.value = "Car repair"
        panel._oneoff_amount.value = "200"
        panel._oneoff_date_display.value = "2026-08-01"
        panel._oneoff_type.value = "expense"
        panel._add_one_off(MagicMock())
        # Transaction added.
        assert len(panel.one_off_transactions) == 1
        txn = panel.one_off_transactions[0]
        assert txn.name == "Car repair"
        assert txn.amount == -200.0
        assert txn.date == date(2026, 8, 1)
        # Form reset.
        assert panel._oneoff_name.value == ""
        assert panel._oneoff_amount.value == ""
        assert panel._oneoff_error.value == ""
        # Date reset to default (today + 7 days).
        expected = (date.today() + timedelta(days=7)).strftime("%Y-%m-%d")
        assert panel._oneoff_date_display.value == expected

    def test_adds_income_when_type_dropdown_set(self, panel):
        panel._oneoff_name.value = "Tax refund"
        panel._oneoff_amount.value = "500"
        panel._oneoff_date_display.value = "2026-04-15"
        panel._oneoff_type.value = "income"
        panel._add_one_off(MagicMock())
        txn = panel.one_off_transactions[0]
        assert txn.amount == 500.0  # positive

    def test_unparseable_date_falls_back_to_picked_date(self, panel):
        panel._oneoff_name.value = "Test"
        panel._oneoff_amount.value = "100"
        panel._oneoff_date_display.value = "garbage"
        panel._oneoff_picked_date = date(2026, 9, 15)
        panel._add_one_off(MagicMock())
        # Falls back to the tracked picked date.
        assert panel.one_off_transactions[0].date == date(2026, 9, 15)


# ---------------------------------------------------------------------------
# Editorial button hover handlers
# ---------------------------------------------------------------------------


def _button_container(button: ft.Control) -> ft.Container:
    """Editorial buttons wrap the clickable Container in ``ft.Semantics``."""
    assert isinstance(button, ft.Semantics)
    inner = button.content
    assert isinstance(inner, ft.Container)
    return inner


class TestCoralButtonHover:
    def test_hover_in_switches_to_coral_deep(self):
        button = coral_button("Save", on_click=lambda _e: None)
        container = _button_container(button)
        _m(container).update = MagicMock()
        # Coral at rest.
        assert container.bgcolor == tokens.CORAL
        # Hover in.
        _m(container.on_hover)(SimpleNamespace(data="true", control=container))
        assert container.bgcolor == tokens.CORAL_DEEP
        # Hover out.
        _m(container.on_hover)(SimpleNamespace(data="false", control=container))
        assert container.bgcolor == tokens.CORAL

    def test_with_icon_renders_icon_plus_label(self):
        button = coral_button("Save", icon=ft.Icons.SAVE, on_click=lambda _e: None)
        container = _button_container(button)
        # Row inside has an Icon and a Text.
        body = container.content
        assert isinstance(body, ft.Row)
        controls = body.controls or []
        kinds = {type(c) for c in controls}
        assert ft.Icon in kinds
        assert ft.Text in kinds


class TestGhostButtonHover:
    def test_hover_in_switches_to_paper_2(self):
        button = ghost_button("Cancel", on_click=lambda _e: None)
        container = _button_container(button)
        _m(container).update = MagicMock()
        assert container.bgcolor == "transparent"
        _m(container.on_hover)(SimpleNamespace(data="true", control=container))
        assert container.bgcolor == tokens.PAPER_2
        _m(container.on_hover)(SimpleNamespace(data="false", control=container))
        assert container.bgcolor == "transparent"


class TestInkButtonHover:
    def test_hover_in_switches_to_ink_2(self):
        button = ink_button("Got it", on_click=lambda _e: None)
        container = _button_container(button)
        _m(container).update = MagicMock()
        assert container.bgcolor == tokens.INK
        _m(container.on_hover)(SimpleNamespace(data="true", control=container))
        assert container.bgcolor == tokens.INK_2
        _m(container.on_hover)(SimpleNamespace(data="false", control=container))
        assert container.bgcolor == tokens.INK


class TestButtonAccessibility:
    """Editorial buttons must remain accessible: wrapped in Semantics
    with a non-empty label. The accessibility regression test already
    enforces this for views; these direct tests document the contract
    for the helpers themselves.
    """

    def test_coral_button_has_semantics_label(self):
        button = coral_button("Save", on_click=lambda _e: None)
        assert isinstance(button, ft.Semantics)
        assert button.button is True
        assert button.label == "Save"

    def test_coral_button_uses_sr_label_when_provided(self):
        button = coral_button(
            "Save", on_click=lambda _e: None, sr_label="Save billing settings for Chase"
        )
        assert isinstance(button, ft.Semantics)
        assert button.label == "Save billing settings for Chase"

    def test_ghost_button_label(self):
        button = ghost_button("Cancel", on_click=lambda _e: None)
        assert isinstance(button, ft.Semantics)
        assert button.label == "Cancel"

    def test_ink_button_label(self):
        button = ink_button("Got it", on_click=lambda _e: None)
        assert isinstance(button, ft.Semantics)
        assert button.label == "Got it"
