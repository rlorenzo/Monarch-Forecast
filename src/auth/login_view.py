"""Login view with email/password and MFA support."""

import logging
from collections.abc import Callable
from typing import Any

import flet as ft
from monarchmoney import LoginFailedException, RequireMFAException

from src.auth.session_manager import SessionManager

logger = logging.getLogger(__name__)


class LoginView(ft.Column):
    """Login form with email, password, and optional MFA fields."""

    def __init__(
        self,
        session_manager: SessionManager,
        # Accept any return type — callers typically pass a lambda that
        # calls ``page.run_task(...)``, which returns a Future. The return
        # value is unused either way.
        on_login_success: Callable[[], Any],
        on_demo: Callable[[], Any],
    ) -> None:
        super().__init__()
        self.session_manager = session_manager
        self.on_login_success = on_login_success
        self.on_demo = on_demo
        self._needs_mfa = False

        self.email_field = ft.TextField(
            label="Email",
            width=350,
            autofocus=True,
        )
        self.password_field = ft.TextField(
            label="Password",
            width=350,
            password=True,
            can_reveal_password=True,
        )
        self.mfa_field = ft.TextField(
            label="MFA Code",
            width=350,
            visible=False,
        )
        self.remember_me = ft.Checkbox(
            label="Remember credentials",
            value=True,
        )
        self.login_text = ft.Text("Sign In")
        self.progress = ft.ProgressRing(visible=False, width=18, height=18, stroke_width=2)
        self.login_button = ft.Button(
            content=ft.Row(
                [self.login_text, self.progress],
                alignment=ft.MainAxisAlignment.CENTER,
                spacing=8,
            ),
            width=350,
            on_click=self._handle_login,
            style=ft.ButtonStyle(
                shape=ft.RoundedRectangleBorder(radius=8),
            ),
        )
        self.demo_button = ft.OutlinedButton(
            content=ft.Text("Try Demo Mode"),
            width=350,
            on_click=lambda _: self.on_demo(),
            tooltip="Explore the app with sample data before signing in",
            style=ft.ButtonStyle(
                shape=ft.RoundedRectangleBorder(radius=8),
            ),
        )
        self.status_text = ft.Text(
            value="",
            color=ft.Colors.RED_400,
            size=13,
        )
        # Wrap the status text in a Semantics live region so assistive tech
        # announces login failures / MFA prompts when status_text.value
        # changes. The inner Container reserves height so the Semantics node
        # has visible content even when status_text is empty (Flet rejects a
        # Semantics whose content collapses to zero size).
        self._status_live_region = ft.Semantics(
            live_region=True,
            content=ft.Container(content=self.status_text, height=18),
        )

        # Pre-fill saved credentials
        email, password = self.session_manager.load_credentials()
        if email:
            self.email_field.value = email
        if password:
            self.password_field.value = password

        self.horizontal_alignment = ft.CrossAxisAlignment.CENTER
        self.alignment = ft.MainAxisAlignment.CENTER
        self.spacing = 0
        self.controls = [
            # Header with gradient background
            ft.Container(
                content=ft.Column(
                    [
                        ft.Icon(ft.Icons.ACCOUNT_BALANCE, size=56, color=ft.Colors.WHITE),
                        ft.Text(
                            "Monarch Forecast",
                            size=28,
                            weight=ft.FontWeight.BOLD,
                            color=ft.Colors.WHITE,
                        ),
                        ft.Text(
                            "See where your money is headed",
                            size=14,
                            color=ft.Colors.with_opacity(0.85, ft.Colors.WHITE),
                        ),
                        ft.Container(height=4),
                        ft.Text(
                            "Project your checking account balance day-by-day using\n"
                            "your Monarch Money data. Spot shortfalls before they happen.",
                            size=12,
                            color=ft.Colors.with_opacity(0.7, ft.Colors.WHITE),
                            text_align=ft.TextAlign.CENTER,
                        ),
                    ],
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    spacing=6,
                ),
                padding=ft.Padding.symmetric(vertical=40, horizontal=24),
                gradient=ft.LinearGradient(
                    begin=ft.Alignment(-1, -1),
                    end=ft.Alignment(1, 1),
                    colors=["#1565C0", "#1E88E5", "#42A5F5"],
                ),
                border_radius=16,
                width=450,
            ),
            # Login form card
            ft.Container(
                content=ft.Column(
                    [
                        ft.Container(height=8),
                        self.email_field,
                        self.password_field,
                        self.mfa_field,
                        ft.Row(
                            [self.remember_me],
                            alignment=ft.MainAxisAlignment.CENTER,
                            width=350,
                        ),
                        self._status_live_region,
                        self.login_button,
                        ft.Container(height=4),
                        ft.Text(
                            "Want to try the app before signing in?",
                            size=11,
                            color=ft.Colors.ON_SURFACE_VARIANT,
                        ),
                        self.demo_button,
                    ],
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    spacing=12,
                ),
                padding=ft.Padding.symmetric(vertical=24, horizontal=24),
            ),
            # Security note
            ft.Container(
                content=ft.Row(
                    [
                        ft.Icon(ft.Icons.LOCK_OUTLINE, size=14, color=ft.Colors.ON_SURFACE_VARIANT),
                        ft.Text(
                            "Credentials are stored in your OS keychain "
                            "(macOS Keychain, Windows Credential Locker, or Linux SecretService). "
                            "Nothing is sent to third parties.",
                            size=11,
                            color=ft.Colors.ON_SURFACE_VARIANT,
                            width=340,
                        ),
                    ],
                    spacing=8,
                    alignment=ft.MainAxisAlignment.CENTER,
                ),
                padding=ft.Padding.only(bottom=16),
            ),
        ]

    async def _handle_login(self, e: ft.Event[ft.Button]) -> None:
        email = (self.email_field.value or "").strip()
        password = (self.password_field.value or "").strip()

        if not email or not password:
            self.status_text.value = "Please enter email and password."
            self.status_text.update()
            # Flet 0.84 made Control.focus() async — await inside this
            # already-async handler.
            await (self.email_field if not email else self.password_field).focus()
            return

        self.login_button.disabled = True
        self.login_text.value = "Signing in..."
        self.progress.visible = True
        self.status_text.value = ""
        self.login_button.update()
        self.status_text.update()

        try:
            if self._needs_mfa:
                mfa_code = (self.mfa_field.value or "").strip()
                if not mfa_code:
                    self.status_text.value = "Please enter your MFA code."
                    await self.mfa_field.focus()
                    return
                await self.session_manager.login_with_mfa(email, password, mfa_code)
            else:
                await self.session_manager.login(email, password)

            if self.remember_me.value:
                self.session_manager.save_credentials(email, password)

            self.on_login_success()

        except RequireMFAException:
            self._needs_mfa = True
            self.mfa_field.visible = True
            self.mfa_field.autofocus = True
            self.status_text.value = "MFA required. Enter your code below."
            self.status_text.color = ft.Colors.ORANGE_400
            self.mfa_field.update()
            await self.mfa_field.focus()

        except LoginFailedException:
            self.status_text.value = "Login failed. Check your credentials."
            self.status_text.color = ft.Colors.RED_400
            await self.password_field.focus()

        except Exception:
            logger.exception("Unexpected error during login")
            self.status_text.value = "Sign-in failed. Please try again."
            self.status_text.color = ft.Colors.RED_400

        finally:
            self.login_button.disabled = False
            self.login_text.value = "Sign In"
            self.progress.visible = False
            self.login_button.update()
            self.status_text.update()
