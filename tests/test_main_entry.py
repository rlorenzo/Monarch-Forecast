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

from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import flet as ft
import pytest

from src import main as main_module
from src.auth.login_view import LoginNotice
from src.views import tokens


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
        # mode. Calling it should not raise. It takes the optional login
        # notice the dashboard hands back (None on a plain sign-out).
        on_logout = mock_dash_cls.call_args.kwargs["on_logout"]
        on_logout(None)

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

    async def test_sign_out_carries_its_notice_through_to_the_login_screen(self):
        """The dashboard's notice has to survive the trip back to login.

        This is the one leg of the feature that cannot be exercised in the
        running app: demo mode's sign-out does not navigate under
        ``FLET_FORCE_WEB_SERVER``, so the wiring is pinned here instead —
        the dashboard hands ``on_logout`` a notice, and the LoginView that
        replaces it must be constructed with that same notice.
        """
        import asyncio

        page = _make_page()
        pending: list[asyncio.Task] = []
        page.run_task = lambda handler, *a, **k: pending.append(
            asyncio.ensure_future(handler(*a, **k))
        )

        with (
            patch("src.main.SessionManager") as mock_sm_cls,
            patch("src.main.DashboardView") as mock_dash_cls,
            patch("src.main.LoginView") as mock_login_cls,
        ):
            mock_sm = MagicMock()
            mock_sm.try_restore_session = AsyncMock(return_value=True)
            mock_sm_cls.return_value = mock_sm
            mock_dash_cls.return_value = MagicMock(load_data=AsyncMock())
            mock_login_cls.return_value = MagicMock()

            await main_module.main(page)

            notice = LoginNotice("Local data erased from this computer.", "#217547")
            mock_dash_cls.call_args.kwargs["on_logout"](notice)
            await asyncio.gather(*pending)

        assert mock_login_cls.call_args.kwargs["notice"] is notice
        mock_sm.logout.assert_called_once()

    async def test_a_failed_credential_wipe_downgrades_the_erase_notice(self):
        """The dashboard cannot see the keychain, so this is the last check.

        ``_erase_local_data`` picks its notice before credentials and the
        session file are touched — those belong to the session manager and
        are dropped here, downstream of it. A locked keychain or an
        unlinkable session.pickle leaves the account reachable from this
        computer, so the "erased" the dashboard chose has to be downgraded
        before the login screen prints it.
        """
        import asyncio

        page = _make_page()
        pending: list[asyncio.Task] = []
        page.run_task = lambda handler, *a, **k: pending.append(
            asyncio.ensure_future(handler(*a, **k))
        )

        with (
            patch("src.main.SessionManager") as mock_sm_cls,
            patch("src.main.DashboardView") as mock_dash_cls,
            patch("src.main.LoginView") as mock_login_cls,
        ):
            mock_sm = MagicMock()
            mock_sm.try_restore_session = AsyncMock(return_value=True)
            mock_sm.logout = MagicMock(return_value=False)
            mock_sm_cls.return_value = mock_sm
            mock_dash_cls.return_value = MagicMock(load_data=AsyncMock())
            mock_login_cls.return_value = MagicMock()

            await main_module.main(page)

            mock_dash_cls.call_args.kwargs["on_logout"](main_module.ERASE_DONE_NOTICE)
            await asyncio.gather(*pending)

        assert mock_login_cls.call_args.kwargs["notice"] == main_module.ERASE_FAILED_NOTICE

    async def test_a_clean_cleanup_leaves_the_erase_notice_alone(self):
        import asyncio

        page = _make_page()
        pending: list[asyncio.Task] = []
        page.run_task = lambda handler, *a, **k: pending.append(
            asyncio.ensure_future(handler(*a, **k))
        )

        with (
            patch("src.main.SessionManager") as mock_sm_cls,
            patch("src.main.DashboardView") as mock_dash_cls,
            patch("src.main.LoginView") as mock_login_cls,
        ):
            mock_sm = MagicMock()
            mock_sm.try_restore_session = AsyncMock(return_value=True)
            mock_sm.logout = MagicMock(return_value=True)
            mock_sm_cls.return_value = mock_sm
            mock_dash_cls.return_value = MagicMock(load_data=AsyncMock())
            mock_login_cls.return_value = MagicMock()

            await main_module.main(page)

            mock_dash_cls.call_args.kwargs["on_logout"](main_module.ERASE_DONE_NOTICE)
            await asyncio.gather(*pending)

        assert mock_login_cls.call_args.kwargs["notice"] == main_module.ERASE_DONE_NOTICE

    async def test_a_failed_cleanup_does_not_invent_a_notice_on_a_plain_sign_out(self):
        """Only the erase promised completeness, so only it gets downgraded.

        A plain sign-out never claimed the credentials were gone from this
        computer; turning a silent sign-out into a red banner would be a
        separate feature, not this fix.
        """
        import asyncio

        page = _make_page()
        pending: list[asyncio.Task] = []
        page.run_task = lambda handler, *a, **k: pending.append(
            asyncio.ensure_future(handler(*a, **k))
        )

        with (
            patch("src.main.SessionManager") as mock_sm_cls,
            patch("src.main.DashboardView") as mock_dash_cls,
            patch("src.main.LoginView") as mock_login_cls,
        ):
            mock_sm = MagicMock()
            mock_sm.try_restore_session = AsyncMock(return_value=True)
            mock_sm.logout = MagicMock(return_value=False)
            mock_sm_cls.return_value = mock_sm
            mock_dash_cls.return_value = MagicMock(load_data=AsyncMock())
            mock_login_cls.return_value = MagicMock()

            await main_module.main(page)

            mock_dash_cls.call_args.kwargs["on_logout"](None)
            await asyncio.gather(*pending)

        assert mock_login_cls.call_args.kwargs["notice"] is None

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
        assert page.fonts == tokens.FONT_ASSETS
        assert page.theme is not None
        assert page.on_keyboard_event is not None
        # The window opens wide enough to draw the transaction ledger's fixed
        # columns uncut. A hardcoded 1100 here used to clip the BALANCE column
        # at the app's own starting size; see tests/test_ledger_width.py.
        assert page.window.width == main_module.LEDGER_UNCLIPPED_WINDOW_WIDTH

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
        # assets_dir is not incidental: it is what makes the "/fonts/..." paths
        # in tokens.FONT_ASSETS resolvable. Drop it and the bundled faces fail
        # to load silently, falling through to the platform fallbacks — a
        # regression with no error message, so it is asserted here.
        mock_run.assert_called_once_with(main_module.main, assets_dir=main_module._ASSETS_DIR)


def _bundled_fonts() -> list[tuple[str, Path]]:
    """Each ``FONT_ASSETS`` entry as (family, on-disk path).

    The values are asset-root-relative because that is what Flet resolves at
    runtime; the leading slash has to come off to read them from the filesystem.
    """
    assets = Path(main_module._ASSETS_DIR)
    return [
        (family, assets / asset_path.removeprefix("/"))
        for family, asset_path in tokens.FONT_ASSETS.items()
    ]


class TestBundledFontAssets:
    """The fonts named in ``FONT_ASSETS`` must exist under the resolved
    assets directory, and ship the licence that lets us redistribute them.

    Both halves are silent when broken: a renamed font file or a moved assets
    directory shows up only as the wrong typeface in a running app, and a
    missing OFL notice shows up only as a licence violation.
    """

    def test_every_font_is_present_and_non_empty(self):
        for family, font in _bundled_fonts():
            assert font.is_file(), f"{family} font missing at {font}"
            assert font.stat().st_size > 0, f"{family} font is empty at {font}"

    def test_every_font_ships_its_ofl_licence(self):
        """The OFL requires the licence to travel with the font, and the
        build sweeps ``assets/`` in wholesale — so the guard belongs here,
        beside the files, not in the packaging workflow."""
        for family, font in _bundled_fonts():
            licence = font.with_name(f"{font.stem}-OFL.txt")
            assert licence.is_file(), f"{family} ships without a licence at {licence}"
            assert "SIL Open Font License" in licence.read_text()

    def test_falls_back_to_the_relative_path_when_assets_are_out_of_reach(
        self, monkeypatch, tmp_path
    ):
        """Packaged builds land the source somewhere the dev-tree ``assets/``
        isn't reachable from. ``ft.run`` must still get a usable path — the
        relative one Flet's own bundled asset server resolves — or the fonts
        fall through to the platform fallbacks with no error."""
        monkeypatch.setattr(main_module, "ASSETS_DIR", tmp_path / "nowhere")

        assert main_module._resolve_assets_dir() == "assets"


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
