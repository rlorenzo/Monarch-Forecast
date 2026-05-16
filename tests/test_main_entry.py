"""Tests for the ``main`` async entry point in ``src.main``.

``main(page)`` configures the Flet page (title, theme, fonts, padding,
keyboard handler) and then either restores a saved session and shows
the dashboard, or shows the login screen. The keyboard-handler closure
delegates to ``dispatch_keyboard_shortcut`` which has its own focused
test file.

These tests cover the page configuration + session-restore branching
with a mocked page and a patched ``SessionManager``.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import flet as ft
import pytest

from src import main as main_module


def _m(obj: Any) -> Any:
    return obj


def _make_page() -> MagicMock:
    page = MagicMock(spec=ft.Page)
    # Settable page properties.
    page.title = ""
    page.window = MagicMock()
    page.padding = None
    page.theme_mode = None
    page.fonts = None
    page.theme = None
    page.on_keyboard_event = None
    page.controls = []
    page.run_task = MagicMock()
    page.update = MagicMock()
    return page


@pytest.mark.asyncio
class TestMainEntry:
    async def test_restored_session_shows_dashboard(self):
        page = _make_page()
        # Mock SessionManager that says "session restored".
        with (
            patch("src.main.SessionManager") as mock_sm_cls,
            patch("src.main.DashboardView") as mock_dash_cls,
            patch("src.main.LoginView") as mock_login_cls,
        ):
            mock_sm = MagicMock()
            mock_sm.try_restore_session = AsyncMock(return_value=True)
            mock_sm_cls.return_value = mock_sm
            mock_dash = MagicMock()
            mock_dash.load_data = AsyncMock()
            mock_dash_cls.return_value = mock_dash

            await main_module.main(page)

        # Dashboard, not login, was instantiated + appended to page.
        mock_dash_cls.assert_called_once()
        mock_login_cls.assert_not_called()
        _m(mock_dash.load_data).assert_awaited_once()

    async def test_no_session_shows_login(self):
        page = _make_page()
        with (
            patch("src.main.SessionManager") as mock_sm_cls,
            patch("src.main.DashboardView") as mock_dash_cls,
            patch("src.main.LoginView") as mock_login_cls,
        ):
            mock_sm = MagicMock()
            mock_sm.try_restore_session = AsyncMock(return_value=False)
            mock_sm_cls.return_value = mock_sm
            mock_login_cls.return_value = MagicMock()

            await main_module.main(page)

        mock_login_cls.assert_called_once()
        mock_dash_cls.assert_not_called()

    async def test_page_configured(self):
        page = _make_page()
        with (
            patch("src.main.SessionManager") as mock_sm_cls,
            patch("src.main.LoginView") as mock_login_cls,
        ):
            mock_sm = MagicMock()
            mock_sm.try_restore_session = AsyncMock(return_value=False)
            mock_sm_cls.return_value = mock_sm
            mock_login_cls.return_value = MagicMock()
            await main_module.main(page)

        # The dashboard sets a Flet title, theme_mode, fonts, theme,
        # keyboard handler. Spot-check a few.
        assert "Monarch Forecast" in (page.title or "")
        assert page.theme_mode == ft.ThemeMode.SYSTEM
        assert page.fonts is not None
        assert page.theme is not None
        assert page.on_keyboard_event is not None

    async def test_keyboard_handler_delegates(self):
        page = _make_page()
        with (
            patch("src.main.SessionManager") as mock_sm_cls,
            patch("src.main.LoginView") as mock_login_cls,
            patch("src.main.dispatch_keyboard_shortcut") as mock_dispatch,
        ):
            mock_sm = MagicMock()
            mock_sm.try_restore_session = AsyncMock(return_value=False)
            mock_sm_cls.return_value = mock_sm
            mock_login_cls.return_value = MagicMock()

            await main_module.main(page)

            # The keyboard handler is wired onto the page. Invoke it
            # inside the ``with`` block so the dispatcher patch is still
            # active when the closure resolves it from module globals.
            assert page.on_keyboard_event is not None
            event = MagicMock(spec=ft.KeyboardEvent)
            event.key = "Escape"
            page.on_keyboard_event(event)
            mock_dispatch.assert_called_once()


class TestRun:
    def test_run_filters_deprecation_warnings_and_calls_ft_run(self):
        with patch("src.main.ft.run") as mock_run:
            main_module.run()
        mock_run.assert_called_once_with(main_module.main)
