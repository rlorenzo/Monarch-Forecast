"""Update notification banner for the dashboard."""

import webbrowser
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlsplit

import flet as ft

from src.utils.updater import check_for_update, get_current_version

_executor = ThreadPoolExecutor(max_workers=1)

# Hosts the Download button is allowed to open. ``download_target`` comes
# from the GitHub-release payload (see ``src.utils.updater``); validating it
# before handing it to ``webbrowser.open`` stops a compromised/spoofed
# release response from launching an arbitrary URL on the user's machine.
_ALLOWED_DOWNLOAD_HOSTS = ("github.com", "githubusercontent.com")


def _is_safe_download_url(url: str) -> bool:
    """True if ``url`` is an https link to github.com or githubusercontent.com."""
    parts = urlsplit(url)
    if parts.scheme != "https":
        return False
    host = parts.hostname or ""
    return any(host == h or host.endswith(f".{h}") for h in _ALLOWED_DOWNLOAD_HOSTS)


async def check_update_async() -> dict | None:
    """Run the update check in a thread to avoid blocking the UI."""
    import asyncio

    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_executor, check_for_update)


def build_update_banner(update_info: dict) -> ft.Container:
    """Build a dismissible update notification banner."""
    version = update_info["version"]
    # First candidate that passes the allowlist wins: an unsafe (spoofed or
    # malformed) asset URL falls through to the release page rather than
    # leaving the Download button a dead no-op.
    candidates = (update_info.get("download_url", ""), update_info.get("html_url", ""))
    download_target = next((u for u in candidates if u and _is_safe_download_url(u)), "")

    def open_download(_: ft.Event[ft.TextButton]) -> None:
        if download_target:
            webbrowser.open(download_target)

    def dismiss(_: ft.Event[ft.IconButton]) -> None:
        banner.visible = False
        try:
            banner.update()
        except (RuntimeError, AssertionError):
            pass  # Control not mounted yet — first paint will pick it up.

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
                ft.Semantics(
                    button=True,
                    label="Dismiss update notification",
                    content=ft.IconButton(
                        icon=ft.Icons.CLOSE,
                        icon_size=18,
                        on_click=dismiss,
                        tooltip="Dismiss",
                    ),
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
