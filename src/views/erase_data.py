"""The "Erase local data" dialog — the destructive counterpart to Sign out.

Sign out deliberately keeps preferences. The exclusions, amount overrides,
and one-off transactions are the user's own work, built up over months, and
dropping them on a routine sign-out would be a regression rather than a
courtesy. Erase is for the other case: handing this computer on, or
clearing an account that was signed in by mistake. It removes everything
Monarch Forecast has ever written here.

Two details of this dialog are deliberate:

- It names what goes, item by item. "Erase local data" alone does not tell
  a user whether their adjustments are included, and they are.
- **Cancel takes focus, not Erase.** AGENTS.md asks a dialog's primary
  action to carry ``autofocus=True`` so focus enters the modal. Here the
  primary action is irreversible, and arming Return to destroy the user's
  data is exactly the accident that guidance exists to prevent. Focus goes
  to the safe action; the modal is still entered, and Escape still closes.
"""

from collections.abc import Callable

import flet as ft

from src.views import tokens
from src.views.adjustments import _dialog_title, dialog_action_button

ERASE_ITEMS = (
    "Your Monarch Money email and password, from this computer's keychain",
    "The saved sign-in session",
    "The cached copy of your accounts and transactions",
    "Your adjustments — excluded recurring items, amount overrides, and one-offs",
    "Your settings, including the selected account and the forecast window",
)

_PREAMBLE = (
    "This removes everything Monarch Forecast has stored on this computer "
    "and signs you out. Nothing in your Monarch Money account is touched."
)

_CLOSING = "This cannot be undone."


def _bullet(text: str) -> ft.Control:
    """One item of the what-goes list, hanging-indented under its marker."""
    return ft.Row(
        controls=[
            ft.Text("·", style=tokens.body_style(tokens.INK_2)),
            ft.Text(text, style=tokens.body_style(tokens.INK_2), expand=True),
        ],
        spacing=8,
        vertical_alignment=ft.CrossAxisAlignment.START,
    )


def show_erase_data_dialog(
    page: ft.Page | ft.BasePage,
    on_confirm: Callable[[], None],
) -> None:
    """Ask for confirmation, then hand control back to ``on_confirm``.

    The dialog does no erasing itself — it only decides. The caller owns
    the deletion and the sign-out that follows, so this module stays
    free of any path or store it would have to keep in sync.
    """

    def handle_cancel(_: ft.Event[ft.Button]) -> None:
        page.pop_dialog()

    def handle_erase(_: ft.Event[ft.Button]) -> None:
        # Pop first: the confirm callback navigates away to the login
        # view, and a dialog left open would outlive the page it was
        # raised from.
        page.pop_dialog()
        on_confirm()

    body: list[ft.Control] = [ft.Text(_PREAMBLE, style=tokens.body_style(tokens.INK))]
    body.extend(_bullet(item) for item in ERASE_ITEMS)
    closing_style = tokens.body_style(tokens.SIGNAL_NEGATIVE)
    closing_style.weight = ft.FontWeight.W_600
    body.append(ft.Text(_CLOSING, style=closing_style))

    dialog = ft.AlertDialog(
        bgcolor=tokens.PAPER,
        title=_dialog_title("Erase local data?"),
        content=ft.Column(body, spacing=10, tight=True, width=460, scroll=ft.ScrollMode.AUTO),
        actions=[
            dialog_action_button(
                "Cancel",
                on_click=handle_cancel,
                bgcolor=tokens.PAPER_2,
                hover_bgcolor=tokens.RULE,
                color=tokens.INK,
                autofocus=True,
            ),
            dialog_action_button(
                "Erase everything",
                on_click=handle_erase,
                bgcolor=tokens.SIGNAL_NEGATIVE,
                hover_bgcolor=tokens.CORAL_DEEP,
            ),
        ],
    )
    page.show_dialog(dialog)
