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


@pytest.fixture(autouse=True)
def _clear_auto_demo_env(monkeypatch):
    """Ensure each test starts with MONARCH_FORECAST_AUTO_DEMO unset.

    Without this, a developer who has the env var exported in their shell
    (e.g. while iterating on the build-time smoke test) would see the
    normal-flow tests below silently take the demo branch — the suite
    must be independent of the caller's environment.
    Tests that need the var set call ``monkeypatch.setenv`` themselves,
    which overrides this fixture's deletion within their scope.
    """
    monkeypatch.delenv("MONARCH_FORECAST_AUTO_DEMO", raising=False)


@pytest.mark.asyncio
class TestAutoDemoEnv:
    """Verify the MONARCH_FORECAST_AUTO_DEMO=1 short-circuit used by the
    build-time smoke test in ``.github/workflows/build.yml``.

    The env var must route directly to the demo dashboard (bypassing
    session restore and login) when set, and must be a no-op when unset
    so production behavior is unaffected.
    """

    async def test_env_routes_to_demo_dashboard(self, monkeypatch):
        page = _make_page()
        monkeypatch.setenv("MONARCH_FORECAST_AUTO_DEMO", "1")
        # ``show_demo_dashboard`` evaluates ``DataCache(db_path=...)`` and
        # ``Preferences(path=...)`` as kwargs before the mocked
        # ``DashboardView`` is even called — without patching them, the
        # test would create files under the user's real ``~/.monarch-forecast``.
        with (
            patch("src.main.SessionManager") as mock_sm_cls,
            patch("src.main.DashboardView") as mock_dash_cls,
            patch("src.main.LoginView") as mock_login_cls,
            patch("src.main.DataCache") as mock_cache_cls,
            patch("src.main.Preferences") as mock_prefs_cls,
            patch("src.main.DemoClient") as mock_demo_client_cls,
        ):
            mock_sm = MagicMock()
            mock_sm.try_restore_session = AsyncMock(return_value=False)
            mock_sm_cls.return_value = mock_sm
            mock_dash = MagicMock()
            mock_dash.load_data = AsyncMock()
            mock_dash_cls.return_value = mock_dash
            mock_cache_cls.return_value = MagicMock()
            mock_prefs_cls.return_value = MagicMock()
            mock_demo_client_cls.return_value = MagicMock()

            await main_module.main(page)

        # Dashboard was instantiated for demo mode — login was never shown,
        # session restore short-circuited. ``load_data`` must also have been
        # awaited so the dashboard isn't displayed empty when the smoke test
        # screenshots it.
        mock_dash_cls.assert_called_once()
        mock_login_cls.assert_not_called()
        _m(mock_sm.try_restore_session).assert_not_called()
        _m(mock_dash.load_data).assert_awaited_once()
        # Auto-demo must short-circuit BEFORE SessionManager is constructed.
        # The lazy ``_get_session_manager`` helper means a real session
        # manager is never instantiated for the smoke-test launch path.
        # (DataCache and Preferences are still created and may touch
        # ~/.monarch-forecast/demo-*; those hold transient demo state
        # and don't leak credentials.)
        mock_sm_cls.assert_not_called()
        # The demo dashboard's on_logout callback must be a callable that
        # resolves at call time — earlier we had a closure over an
        # unbound ``show_login`` that crashed when invoked in auto-demo
        # mode. Calling it should not raise.
        on_logout = mock_dash_cls.call_args.kwargs["on_logout"]
        on_logout()

    async def test_env_unset_uses_normal_flow(self):
        # _clear_auto_demo_env (autouse) ensures the env var is unset.
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

        # Normal flow: session restore runs, login shows, demo dashboard not used.
        _m(mock_sm.try_restore_session).assert_awaited_once()
        mock_login_cls.assert_called_once()
        mock_dash_cls.assert_not_called()


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
        # LIGHT until the dark token ramp is wired into the views; SYSTEM
        # would hand dark-OS users ink text on Material's default dark.
        assert page.theme_mode == ft.ThemeMode.LIGHT
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


class TestRootEntryPoint:
    """Guard the root ``main.py`` wrapper that ``flet build`` compiles into
    the shipped ``main.pyc``.

    The local CLI uses ``[project.scripts] monarch-forecast = "src.main:run"``,
    so a broken wrapper at the repo root is invisible to ``uv run`` and to
    every other unit test — they all exercise ``src.main`` directly. The
    packaged app, however, runs ``main.pyc`` (compiled from the root
    ``main.py``) under ``serious_python``: if the wrapper imports ``main``
    but never calls anything, the Python process exits in milliseconds and
    the Flutter shell briefly opens a window before closing — the
    "opens and then closes" symptom of the 1.0.0 release.

    This test runpy-executes ``main.py`` as ``__main__`` with ``ft.run``
    patched out and asserts the wrapper actually starts Flet.
    """

    def test_root_main_py_invokes_ft_run(self):
        import runpy
        from pathlib import Path

        root_main = Path(__file__).resolve().parent.parent / "main.py"
        assert root_main.exists(), "root main.py is the flet build entry point"

        with patch("src.main.ft.run") as mock_run:
            runpy.run_path(str(root_main), run_name="__main__")

        mock_run.assert_called_once()
