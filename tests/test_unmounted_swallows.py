"""Exercise the ``try/except RuntimeError: pass`` swallows around
unmounted ``.update()`` calls.

Most other tests stub ``.update()`` to a MagicMock so the try block
runs cleanly and the except branch never fires. This file deliberately
leaves ``.update()`` un-stubbed so the unmounted-control RuntimeError
hits the swallow path.

These are defensive branches the dashboard and panel rely on whenever
a handler runs before mount (e.g. during construction) or during a
tear-down race.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import flet as ft
import pytest

from src.data.preferences import Preferences
from src.views.adjustments import (
    AdjustmentsPanel,
    _section_header,
)
from src.views.dashboard import DashboardView


def _m(obj: Any) -> Any:
    return obj


# ---------------------------------------------------------------------------
# _section_header clickable on_hover — same try/except
# ---------------------------------------------------------------------------


class TestSectionHeaderHoverSwallowsRuntimeError:
    def test_clickable_section_header_hover_unmounted(self):
        header = _section_header(
            "EYEBROW",
            "Title",
            "Subtitle",
            on_click=lambda _e: None,
        )
        # The clickable variant is a Semantics(button) around the hover Container.
        assert isinstance(header, ft.Semantics)
        assert header.button is True
        assert header.label == "Title"
        box = header.content
        assert isinstance(box, ft.Container)
        _m(box.on_hover)(SimpleNamespace(data="true", control=box))
        _m(box.on_hover)(SimpleNamespace(data="false", control=box))


# ---------------------------------------------------------------------------
# Dashboard hover handlers
# ---------------------------------------------------------------------------


@pytest.fixture
def dashboard(patched_session_manager, tmp_path: Path):
    prefs = Preferences(path=tmp_path / "prefs.json")
    prefs.set_onboarding_seen(True)
    dash = DashboardView(
        session_manager=patched_session_manager,
        on_logout=MagicMock(),
        preferences=prefs,
    )
    setattr(dash, "_run_task", MagicMock())  # noqa: B010
    return dash


class TestDashboardButtons:
    def test_add_one_off_button_is_focusable_button(self, dashboard):
        button = dashboard._add_one_off_button
        assert isinstance(button, ft.Semantics)
        assert isinstance(button.content, ft.Button)
        assert button.label == "Add a one-off transaction"

    def test_dialog_dismiss_button_is_focusable_button(self, dashboard):
        button = dashboard._build_dialog_dismiss_button("Got it", on_click=lambda _e: None)
        assert isinstance(button, ft.Semantics)
        assert isinstance(button.content, ft.Button)


# ---------------------------------------------------------------------------
# AdjustmentsPanel meta chip (private helper)
# ---------------------------------------------------------------------------


class TestMetaChipHelper:
    def test_meta_chip_returns_container(self):
        from src.views.adjustments import _meta_chip

        chip = _meta_chip("3 of 12 included")
        assert isinstance(chip, ft.Container)
        # The inner Text carries the count.
        inner = chip.content
        assert isinstance(inner, ft.Text)
        assert inner.value == "3 OF 12 INCLUDED"


# ---------------------------------------------------------------------------
# Stragglers in adjustments.py: dialog calendar handler when on_pick fires
# without a typed canonicalisation update
# ---------------------------------------------------------------------------


class TestPanelOneOffDateTypedNoChange:
    """``_on_oneoff_date_typed`` short-circuits when the typed text doesn't
    parse — no update call is made. Test that path completes cleanly.
    """

    def test_unchanged_value_when_unparseable(self, tmp_path: Path):
        prefs = Preferences(path=tmp_path / "p.json")
        panel = AdjustmentsPanel(recurring_items=[], on_change=lambda: None, preferences=prefs)
        panel._oneoff_date_display.value = "still bad"
        prior = panel._oneoff_picked_date
        panel._on_oneoff_date_typed(MagicMock())
        assert panel._oneoff_picked_date == prior
        # Value untouched.
        assert panel._oneoff_date_display.value == "still bad"


# ---------------------------------------------------------------------------
# Dashboard alerts no-forecast guard
# ---------------------------------------------------------------------------


class TestUpdateAlertsNoForecast:
    def test_no_forecast_clears_banner(self, dashboard):
        dashboard._forecast = None
        # Seed something so we can verify it gets cleared.
        dashboard.alerts_container.content = ft.Text("stale")
        dashboard._update_alerts()
        assert dashboard.alerts_container.content is None


# ---------------------------------------------------------------------------
# Dashboard _show_snackbar attribute-error swallow
# ---------------------------------------------------------------------------


class TestShowSnackbarAttributeErrorSwallow:
    def test_no_page_attribute_swallows(self, dashboard):
        # Real ``_show_snackbar`` swallows AttributeError when ``page``
        # raises on access. Without a mounted dashboard, ``self.page``
        # raises RuntimeError which is also caught.
        dashboard._show_snackbar("hello")  # should not raise


# ---------------------------------------------------------------------------
# Dashboard chevron toggle handlers
# ---------------------------------------------------------------------------


class TestCCSectionToggleUnmounted:
    def test_toggle_with_unmounted_widgets_swallows_update(self, dashboard):
        # Build the widgets manually so toggle has something to mutate,
        # but don't mount them. The update() inside _safe_update is
        # already RuntimeError-tolerant.
        dashboard._cc_chevron = ft.Icon(ft.Icons.KEYBOARD_ARROW_RIGHT)
        dashboard._cc_cards_wrapper = ft.Container(visible=False)
        # Direct call — no patches.
        dashboard._toggle_cc_section(MagicMock())
        assert dashboard._cc_section_expanded is True
