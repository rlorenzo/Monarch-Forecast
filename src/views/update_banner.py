"""Update notification banner for the dashboard."""

import webbrowser
from concurrent.futures import ThreadPoolExecutor

import flet as ft

from src.utils.updater import check_for_update, get_current_version

_executor = ThreadPoolExecutor(max_workers=1)


async def check_update_async() -> dict | None:
    """Run the update check in a thread to avoid blocking the UI."""
    import asyncio

    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_executor, check_for_update)


def build_update_banner(update_info: dict) -> ft.Container:
    """Build a dismissible update notification banner."""
    version = update_info["version"]
    download_target = update_info.get("download_url", update_info.get("html_url", ""))

    def open_download(_: ft.ControlEvent) -> None:
        if download_target:
            webbrowser.open(download_target)

    def dismiss(e: ft.ControlEvent) -> None:
        banner.visible = False
        banner.update()

    banner = ft.Container(
        content=ft.Row(
            [
                ft.Icon(ft.Icons.SYSTEM_UPDATE, color=ft.Colors.PRIMARY, size=22),
                ft.Column(
                    [
                        ft.Text(
                            f"Version {version} available",
                            weight=ft.FontWeight.BOLD,
                            size=13,
                        ),
                        ft.Text(
                            f"You're running v{get_current_version()}. "
                            "Download the latest version for new features and fixes.",
                            size=12,
                        ),
                    ],
                    spacing=2,
                    expand=True,
                ),
                ft.TextButton("Download", on_click=open_download),
                ft.IconButton(
                    icon=ft.Icons.CLOSE,
                    icon_size=18,
                    on_click=dismiss,
                    tooltip="Dismiss",
                ),
            ],
            spacing=12,
        ),
        padding=12,
        bgcolor=ft.Colors.PRIMARY_CONTAINER,
        border=ft.Border.all(1, ft.Colors.PRIMARY),
        border_radius=8,
    )
    return banner
