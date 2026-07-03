"""Monarch Forecast - Financial forecasting desktop app."""

import os
from pathlib import Path

import flet as ft

from src.auth.login_view import LoginView
from src.auth.session_manager import DemoSessionManager, SessionManager
from src.data import demo_data
from src.data.cache import DataCache
from src.data.demo_client import DemoClient
from src.data.preferences import Preferences
from src.utils.updater import get_current_version
from src.views import tokens
from src.views.dashboard import DashboardView


def dispatch_keyboard_shortcut(
    event: ft.KeyboardEvent,
    page: ft.Page,
    dashboard: DashboardView | None,
) -> bool:
    """Pure dispatch logic for the global keyboard shortcuts.

    Extracted from the inline ``handle_keyboard`` closure so the routing
    behavior is exercised in tests without spinning up a Flet event loop.

    Returns ``True`` when the event was handled (a shortcut fired or
    Escape closed a dialog) and ``False`` when the event should
    propagate. The caller still owns wiring this onto
    ``page.on_keyboard_event``.

    - Escape pops the current dialog (Flet's AlertDialog doesn't bind it).
    - Cmd/Ctrl+R triggers a refresh on the dashboard.
    - Cmd/Ctrl+1/2/3 jumps to the matching tab.
    - Cmd/Ctrl+4 cycles the Transactions tab through Upcoming/Recent/Both.
    """
    if event.key == "Escape":
        try:
            page.pop_dialog()
        except Exception:
            pass  # No dialog open — harmless.
        return True

    # Cmd on macOS is surfaced as `meta`, Ctrl on Windows/Linux as `ctrl`.
    if not (event.ctrl or event.meta):
        return False
    if dashboard is None:
        return False

    if event.key in ("R", "r"):
        dashboard.trigger_refresh()
        return True
    if event.key == "1":
        dashboard.switch_to_tab(0)
        return True
    if event.key == "2":
        dashboard.switch_to_tab(1)
        return True
    if event.key == "3":
        dashboard.switch_to_tab(2)
        return True
    if event.key == "4":
        # The mode chips are mouse targets; this is the keyboard path
        # through the Transactions tab's Upcoming/Recent/Both modes.
        dashboard.toggle_txn_mode()
        return True

    return False


_DATA_DIR = Path.home() / ".monarch-forecast"
DEMO_CACHE_DB = _DATA_DIR / "demo-cache.db"
DEMO_PREFS_FILE = _DATA_DIR / "demo-preferences.json"


async def main(page: ft.Page) -> None:
    page.title = f"Monarch Forecast v{get_current_version()}"
    page.window.width = 1100
    page.window.height = 900
    # 900, not 800: the transaction ledgers' fixed column set is ~890px
    # wide and the scroll region only scrolls vertically, so a narrower
    # window clips the AMOUNT column.
    page.window.min_width = 900
    page.window.min_height = 600
    page.window.icon = "assets/icon.png"
    page.padding = ft.Padding.only(left=0, top=0, right=16, bottom=8)
    # LIGHT, not SYSTEM: only the light paper-and-ink theme is defined
    # below, and every view paints with the light token constants. Under
    # SYSTEM, a dark-OS machine gets Material's default dark surfaces with
    # near-black ink text on them — unreadable. Flip back to SYSTEM only
    # when the dark ramp in tokens.py is actually consumed by the views.
    page.theme_mode = ft.ThemeMode.LIGHT
    page.fonts = tokens.FONT_URLS

    _icon_theme = ft.IconTheme(apply_text_scaling=True)

    # Step 5 of bisect: explicit ColorScheme replaces color_scheme_seed.
    # Light theme only for now; dark theme stays Material default.
    page.theme = ft.Theme(
        color_scheme=ft.ColorScheme(
            primary=tokens.CORAL,
            on_primary=tokens.PAPER,
            primary_container=tokens.CORAL_TINT,
            on_primary_container=tokens.CORAL_DEEP,
            secondary=tokens.INK_2,
            on_secondary=tokens.PAPER,
            tertiary=tokens.SIGNAL_THRESHOLD,
            on_tertiary=tokens.INK,
            error=tokens.SIGNAL_NEGATIVE,
            on_error=tokens.PAPER,
            surface=tokens.PAPER,
            on_surface=tokens.INK,
            on_surface_variant=tokens.INK_2,
            surface_container_low=tokens.PAPER,
            surface_container=tokens.PAPER_2,
            surface_container_high=tokens.PAPER_2,
            surface_container_highest=tokens.PAPER_3,
            outline=tokens.RULE,
            outline_variant=tokens.RULE,
        ),
        icon_theme=_icon_theme,
    )

    def _current_dashboard() -> DashboardView | None:
        """Return the mounted dashboard view, if any, for shortcut dispatch."""
        for ctrl in page.controls:
            if isinstance(ctrl, DashboardView):
                return ctrl
        return None

    def handle_keyboard(e: ft.KeyboardEvent) -> None:
        dispatch_keyboard_shortcut(e, page, _current_dashboard())

    page.on_keyboard_event = handle_keyboard

    # SessionManager is created lazily so the auto-demo short-circuit
    # below doesn't pay the cost of initialising a real Monarch client
    # and OS keychain handle. Once any non-demo path needs it, the same
    # instance is reused for the rest of the session.
    session_manager: SessionManager | None = None

    def _get_session_manager() -> SessionManager:
        nonlocal session_manager
        if session_manager is None:
            session_manager = SessionManager()
        return session_manager

    async def show_demo_dashboard() -> None:
        """Open the dashboard with synthetic data — no Monarch account needed.

        Logging out of demo mode returns to the login screen rather than
        clearing real credentials, since there are none to clear. The
        ``show_login`` callback below is referenced lazily, so it's safe
        for this function to run from the auto-demo short-circuit before
        the normal-flow setup runs.
        """
        page.controls.clear()
        # Wipe the cache so edits to demo_data.py are picked up on next
        # launch instead of shadowed by the 30-minute TTL.
        DEMO_CACHE_DB.unlink(missing_ok=True)
        # Re-seed one-offs every launch: their dates are relative to
        # today, so a previously-saved set would have rolled into the
        # past and been filtered out.
        demo_prefs = Preferences(path=DEMO_PREFS_FILE)
        demo_prefs.set_one_off_transactions(demo_data.build_one_off_transactions())
        dashboard = DashboardView(
            session_manager=DemoSessionManager(),
            on_logout=lambda: page.run_task(show_login),
            raw_client=DemoClient(),
            cache=DataCache(db_path=DEMO_CACHE_DB),
            preferences=demo_prefs,
        )
        page.controls.append(dashboard)
        page.update()
        await dashboard.load_data()

    async def do_logout() -> None:
        _get_session_manager().logout()
        await show_login()

    async def show_dashboard() -> None:
        page.controls.clear()
        dashboard = DashboardView(
            session_manager=_get_session_manager(),
            on_logout=lambda: page.run_task(do_logout),
        )
        page.controls.append(dashboard)
        page.update()
        await dashboard.load_data()

    async def show_login() -> None:
        page.controls.clear()
        login_view = LoginView(
            session_manager=_get_session_manager(),
            on_login_success=lambda: page.run_task(show_dashboard),
            on_demo=lambda: page.run_task(show_demo_dashboard),
        )
        page.controls.append(
            ft.Container(
                content=login_view,
                alignment=ft.Alignment(0, 0),
                expand=True,
            )
        )
        page.update()

    # MONARCH_FORECAST_AUTO_DEMO=1 short-circuits straight to demo mode.
    # Used by the build-time smoke test in .github/workflows/build.yml to
    # exercise the dashboard render path without needing real credentials.
    # SessionManager is not constructed; DataCache and Preferences are
    # still created under ``~/.monarch-forecast`` (specifically the
    # ``demo-*`` files) — they hold transient demo-mode state and don't
    # leak credentials.
    if os.environ.get("MONARCH_FORECAST_AUTO_DEMO") == "1":
        await show_demo_dashboard()
        return

    # Try restoring saved session first. Show an inline progress bar while
    # we wait — `page.splash` was removed in Flet 0.80+, so we just append
    # a ProgressBar and clear it when the restore completes.
    splash = ft.ProgressBar()
    page.controls.append(splash)
    page.update()

    restored = await _get_session_manager().try_restore_session()
    page.controls.remove(splash)

    if restored:
        await show_dashboard()
    else:
        await show_login()


def run() -> None:
    import warnings

    warnings.filterwarnings(
        "ignore",
        category=DeprecationWarning,
        message=".*variable_values.*operation_name.*deprecated.*",
    )
    ft.run(main)


if __name__ == "__main__":
    run()
