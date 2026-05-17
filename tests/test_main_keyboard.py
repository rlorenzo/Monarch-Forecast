"""Tests for the global keyboard-shortcut dispatch.

``dispatch_keyboard_shortcut`` is extracted from ``main.handle_keyboard``
so the routing logic can be exercised without a real Flet event loop or
DashboardView.

Covers:

- Escape closes the current dialog (and swallows the no-dialog case).
- Cmd/Ctrl+R refreshes the dashboard.
- Cmd/Ctrl+1/2/3 switches tabs.
- Modifierless keys (and Cmd/Ctrl with no dashboard) are ignored.
"""

from __future__ import annotations

from typing import Any, cast
from unittest.mock import MagicMock

import flet as ft

from src.main import dispatch_keyboard_shortcut


def _event(key: str, *, ctrl: bool = False, meta: bool = False) -> ft.KeyboardEvent:
    """Build a minimal KeyboardEvent stub for the dispatcher.

    The dispatcher only reads ``.key``, ``.ctrl``, and ``.meta`` — a
    SimpleNamespace would suffice, but for type-checker friendliness we
    cast through ``Any``.
    """
    obj = MagicMock(spec=ft.KeyboardEvent)
    obj.key = key
    obj.ctrl = ctrl
    obj.meta = meta
    return cast(ft.KeyboardEvent, obj)


def _make_page() -> MagicMock:
    page = MagicMock(spec=ft.Page)
    page.pop_dialog = MagicMock()
    return page


def _make_dashboard() -> MagicMock:
    dash = MagicMock()
    dash.trigger_refresh = MagicMock()
    dash.switch_to_tab = MagicMock()
    return cast(Any, dash)


class TestEscape:
    def test_escape_pops_dialog(self):
        page = _make_page()
        dash = _make_dashboard()
        handled = dispatch_keyboard_shortcut(_event("Escape"), page, dash)
        assert handled is True
        page.pop_dialog.assert_called_once()

    def test_escape_swallows_pop_error(self):
        page = _make_page()
        page.pop_dialog.side_effect = RuntimeError("no dialog")
        handled = dispatch_keyboard_shortcut(_event("Escape"), page, None)
        assert handled is True  # still treated as handled

    def test_escape_works_without_dashboard(self):
        page = _make_page()
        handled = dispatch_keyboard_shortcut(_event("Escape"), page, None)
        assert handled is True
        page.pop_dialog.assert_called_once()


class TestRefresh:
    def test_cmd_r_triggers_refresh(self):
        page = _make_page()
        dash = _make_dashboard()
        handled = dispatch_keyboard_shortcut(_event("R", meta=True), page, dash)
        assert handled is True
        dash.trigger_refresh.assert_called_once()

    def test_ctrl_r_triggers_refresh(self):
        page = _make_page()
        dash = _make_dashboard()
        handled = dispatch_keyboard_shortcut(_event("r", ctrl=True), page, dash)
        assert handled is True
        dash.trigger_refresh.assert_called_once()

    def test_r_alone_does_not_refresh(self):
        page = _make_page()
        dash = _make_dashboard()
        handled = dispatch_keyboard_shortcut(_event("r"), page, dash)
        assert handled is False
        dash.trigger_refresh.assert_not_called()


class TestTabSwitch:
    def test_cmd_1_switches_to_overview(self):
        page = _make_page()
        dash = _make_dashboard()
        assert dispatch_keyboard_shortcut(_event("1", meta=True), page, dash) is True
        dash.switch_to_tab.assert_called_once_with(0)

    def test_cmd_2_switches_to_transactions(self):
        page = _make_page()
        dash = _make_dashboard()
        assert dispatch_keyboard_shortcut(_event("2", meta=True), page, dash) is True
        dash.switch_to_tab.assert_called_once_with(1)

    def test_cmd_3_switches_to_adjustments(self):
        page = _make_page()
        dash = _make_dashboard()
        assert dispatch_keyboard_shortcut(_event("3", meta=True), page, dash) is True
        dash.switch_to_tab.assert_called_once_with(2)

    def test_cmd_4_unhandled(self):
        page = _make_page()
        dash = _make_dashboard()
        assert dispatch_keyboard_shortcut(_event("4", meta=True), page, dash) is False
        dash.switch_to_tab.assert_not_called()


class TestNoDashboard:
    def test_cmd_r_without_dashboard_unhandled(self):
        page = _make_page()
        assert dispatch_keyboard_shortcut(_event("R", meta=True), page, None) is False

    def test_cmd_1_without_dashboard_unhandled(self):
        page = _make_page()
        assert dispatch_keyboard_shortcut(_event("1", meta=True), page, None) is False


class TestArbitraryKeys:
    def test_unmodified_letter_ignored(self):
        page = _make_page()
        dash = _make_dashboard()
        assert dispatch_keyboard_shortcut(_event("a"), page, dash) is False

    def test_modifier_with_unmapped_key_unhandled(self):
        page = _make_page()
        dash = _make_dashboard()
        assert dispatch_keyboard_shortcut(_event("X", meta=True), page, dash) is False
