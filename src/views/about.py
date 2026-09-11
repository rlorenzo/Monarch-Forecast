"""The About dialog — version, licence, and the Monarch Money disclaimer.

The disclaimer is the point of this dialog, not a footnote. The app talks
to Monarch Money through an unofficial, reverse-engineered API using
credentials the user hands over, and Monarch's terms restrict both
programmatic access and password sharing. Users deserve to be told that
plainly, inside the app, rather than only in a README they may never have
read. The same text lives under "Disclaimer" in ``README.md``; keep the
two in sync.
"""

import webbrowser

import flet as ft

from src.utils.updater import get_current_version
from src.views import tokens
from src.views.adjustments import _dialog_title, dialog_action_button

REPO_URL = "https://github.com/rlorenzo/Monarch-Forecast"
MONARCH_URL = "https://www.monarchmoney.com/"

# Only the URLs this dialog itself renders may be opened. ``on_tap_link``
# hands back whatever href the Markdown renderer parsed, and the body text
# is a module constant, so an allowlist costs nothing and keeps the
# handler from ever becoming a general-purpose URL opener.
_ALLOWED_LINKS = frozenset({REPO_URL, MONARCH_URL})

DISCLAIMER = (
    "**Monarch Forecast is not affiliated with Monarch Money.** It is an "
    "independent, unofficial companion app — not made, endorsed, sponsored, "
    f"or supported by [Monarch Money]({MONARCH_URL}). *Monarch* and *Monarch "
    "Money* are their marks, used here only to say what this app connects to."
    "\n\n"
    "Monarch offers no public API, so this app signs in with the credentials "
    "you supply and reads your data through a reverse-engineered client the "
    "community maintains. Monarch's terms of service restrict both "
    "programmatic access and password sharing. Using this app is your "
    "decision, and Monarch may change or block that access at any time."
    "\n\n"
    "Your data stays on this computer: credentials in your OS keychain, the "
    "cache in a local SQLite file. The app reaches the network for two things "
    "only: your requests to Monarch's own servers, and a version check "
    "against GitHub."
)


def _md_style() -> ft.MarkdownStyleSheet:
    """Inter body copy with coral links, so the dialog matches the app.

    Flet's Markdown otherwise falls back to Flutter's defaults — a system
    sans on Material blue. ``CORAL_DEEP`` on ``PAPER`` measures 5.7:1
    (AA at any size) and the underline carries the link affordance for
    anyone who can't see the hue.
    """
    body = tokens.body_style(tokens.INK)
    link = tokens.body_style(tokens.CORAL_DEEP)
    link.decoration = ft.TextDecoration.UNDERLINE
    return ft.MarkdownStyleSheet(p_text_style=body, a_text_style=link)


def _open_link(e: ft.Event[ft.Markdown]) -> None:
    url = e.data or ""
    if url in _ALLOWED_LINKS:
        webbrowser.open(url)


def show_about_dialog(page: ft.Page | ft.BasePage) -> None:
    """Open the About dialog."""

    def handle_close(_: ft.Event[ft.Button]) -> None:
        page.pop_dialog()

    # ``MarkdownStyleSheet`` is a plain dataclass, not a control, so one
    # instance can back both Markdown blocks.
    md_style = _md_style()
    dialog = ft.AlertDialog(
        bgcolor=tokens.PAPER,
        title=_dialog_title("About Monarch Forecast"),
        content=ft.Column(
            [
                ft.Text(
                    f"Version {get_current_version()} · MIT licence",
                    style=tokens.body_style(tokens.INK_2),
                ),
                ft.Markdown(
                    DISCLAIMER,
                    selectable=True,
                    md_style_sheet=md_style,
                    on_tap_link=_open_link,
                ),
                ft.Markdown(
                    f"[Source code and issue tracker]({REPO_URL})",
                    md_style_sheet=md_style,
                    on_tap_link=_open_link,
                ),
            ],
            spacing=12,
            tight=True,
            width=460,
            scroll=ft.ScrollMode.AUTO,
        ),
        actions=[dialog_action_button("Close", on_click=handle_close, autofocus=True)],
    )
    page.show_dialog(dialog)
