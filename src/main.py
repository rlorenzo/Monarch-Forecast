"""Monarch Forecast - Financial forecasting desktop app."""

import flet as ft

from src.auth.login_view import LoginView
from src.auth.session_manager import SessionManager
from src.views.dashboard import DashboardView


async def main(page: ft.Page) -> None:
    page.title = "Monarch Forecast"
    page.window.width = 1100
    page.window.height = 750
    page.window.min_width = 800
    page.window.min_height = 600
    page.padding = 24
    page.theme_mode = ft.ThemeMode.SYSTEM
    page.theme = ft.Theme(
        color_scheme_seed=ft.Colors.BLUE,
    )

    session_manager = SessionManager()

    async def show_dashboard() -> None:
        page.controls.clear()
        dashboard = DashboardView(
            session_manager=session_manager,
            on_logout=lambda: page.run_task(show_login),
        )
        page.controls.append(dashboard)
        page.update()
        await dashboard.load_data()

    async def show_login() -> None:
        page.controls.clear()
        login_view = LoginView(
            session_manager=session_manager,
            on_login_success=lambda: page.run_task(show_dashboard),
        )
        page.controls.append(
            ft.Container(
                content=login_view,
                alignment=ft.alignment.center,
                expand=True,
            )
        )
        page.update()

    # Try restoring saved session first
    page.splash = ft.ProgressBar()
    page.update()

    restored = await session_manager.try_restore_session()
    page.splash = None

    if restored:
        await show_dashboard()
    else:
        await show_login()


def run() -> None:
    ft.app(target=main)


if __name__ == "__main__":
    run()
