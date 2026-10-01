"""Login view with email/password and MFA support."""

import logging
from collections.abc import Callable
from typing import Any, NamedTuple

import flet as ft
from monarchmoney import (
    CaptchaRequiredException,
    LoginFailedException,
    RequireMFAException,
)

from src.auth.session_manager import SessionManager

logger = logging.getLogger(__name__)

# Named so the test can assert against it rather than substring-matching a
# domain literal, which CodeQL reads as incomplete URL sanitization
# (py/incomplete-url-substring-sanitization). One source of truth for the
# wording is the better arrangement regardless.
CAPTCHA_STATUS_MESSAGE = (
    "Monarch asked for a captcha. Sign in at monarchmoney.com in your browser, then try again here."
)


class LoginNotice(NamedTuple):
    """A message to show on the login screen the moment it opens.

    The dashboard is torn down before the login view is built, so anything
    it still needs to tell the user — a cache it could not clear, an erase
    that succeeded — has to travel as data rather than as a control. The
    status line is already a Semantics live region, so a notice delivered
    this way is announced to screen readers like any sign-in failure.
    """

    message: str
    color: str


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
        notice: LoginNotice | None = None,
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
            autofill_hints=ft.AutofillHint.EMAIL,
        )
        self.password_field = ft.TextField(
            label="Password",
            width=350,
            password=True,
            can_reveal_password=True,
            autofill_hints=ft.AutofillHint.PASSWORD,
        )
        self.mfa_field = ft.TextField(
            label="MFA Code",
            width=350,
            visible=False,
            autofill_hints=ft.AutofillHint.ONE_TIME_CODE,
        )
        # Group email + password so OS password managers (macOS Keychain,
        # 1Password, Bitwarden, etc.) recognise them as a single credential
        # record. ``dispose_action`` starts as CANCEL so we don't prompt to
        # save when the user clicks Demo, the login fails, or "Remember
        # credentials" is unchecked — ``_handle_login`` flips it to COMMIT
        # only on a successful sign-in with that box checked. The MFA
        # field is intentionally outside the group: it's a one-time code,
        # not a stored credential.
        self._autofill_group = ft.AutofillGroup(
            content=ft.Column(
                [self.email_field, self.password_field],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=12,
            ),
            dispose_action=ft.AutofillGroupDisposeAction.CANCEL,
        )
        # Off by default: persisting the raw password is opt-in. The saved
        # session token already gives automatic sign-in on the next launch.
        self.remember_me = ft.Checkbox(
            label="Remember credentials",
            value=False,
        )
        self.login_text = ft.Text(
            "Sign In",
            theme_style=ft.TextThemeStyle.TITLE_MEDIUM,
            color=ft.Colors.ON_PRIMARY,
        )
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
                shadow_color="transparent",
                shape=ft.RoundedRectangleBorder(radius=6),
                bgcolor=ft.Colors.PRIMARY,
                color=ft.Colors.ON_PRIMARY,
            ),
        )
        self.demo_button = ft.OutlinedButton(
            content=ft.Text(
                "Try Demo Mode",
                theme_style=ft.TextThemeStyle.TITLE_MEDIUM,
                color=ft.Colors.ON_SURFACE,
            ),
            width=350,
            on_click=lambda _: self.on_demo(),
            tooltip="Explore the app with sample data before signing in",
            style=ft.ButtonStyle(
                shadow_color="transparent",
                shape=ft.RoundedRectangleBorder(radius=6),
                side=ft.BorderSide(1, ft.Colors.OUTLINE),
                color=ft.Colors.ON_SURFACE,
            ),
        )
        self.status_text = ft.Text(
            value=notice.message if notice else "",
            color=notice.color if notice else ft.Colors.ERROR,
            theme_style=ft.TextThemeStyle.BODY_SMALL,
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
        # Scroll so the form and Demo button are never clipped at the 600px
        # minimum window height.
        self.scroll = ft.ScrollMode.AUTO
        self.controls = [
            # Paper-and-ink wordmark header, matching the side-nav: caps
            # eyebrow, serif title, short coral underscore.
            ft.Container(
                content=ft.Column(
                    [
                        ft.Text(
                            "MONARCH",
                            theme_style=ft.TextThemeStyle.LABEL_SMALL,
                            color=ft.Colors.ON_SURFACE_VARIANT,
                            semantics_label="Monarch Forecast",
                        ),
                        ft.Text(
                            "Forecast",
                            theme_style=ft.TextThemeStyle.DISPLAY_SMALL,
                            color=ft.Colors.ON_SURFACE,
                        ),
                        ft.Container(width=24, height=2, bgcolor=ft.Colors.PRIMARY),
                        ft.Container(height=8),
                        ft.Text(
                            "See where your money is headed",
                            theme_style=ft.TextThemeStyle.BODY_MEDIUM,
                            color=ft.Colors.ON_SURFACE,
                        ),
                        ft.Text(
                            "Project your checking account balance day-by-day using\n"
                            "your Monarch Money data. Spot shortfalls before they happen.",
                            theme_style=ft.TextThemeStyle.BODY_SMALL,
                            color=ft.Colors.ON_SURFACE_VARIANT,
                            text_align=ft.TextAlign.CENTER,
                        ),
                    ],
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    spacing=4,
                ),
                padding=ft.Padding.symmetric(vertical=32, horizontal=24),
                width=450,
            ),
            # Login form card
            ft.Container(
                content=ft.Column(
                    [
                        ft.Container(height=8),
                        self._autofill_group,
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
                            theme_style=ft.TextThemeStyle.LABEL_SMALL,
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
                        ft.Icon(ft.Icons.LOCK_OUTLINE, size=16, color=ft.Colors.ON_SURFACE_VARIANT),
                        ft.Text(
                            "Credentials are stored in your OS keychain "
                            "(macOS Keychain, Windows Credential Locker, or Linux SecretService). "
                            "Nothing is sent to third parties.",
                            theme_style=ft.TextThemeStyle.LABEL_SMALL,
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
                # Opt into the OS password manager "save password?" prompt
                # only when the user has chosen to remember credentials.
                # ``.update()`` flushes the new dispose_action to Flutter
                # before ``on_login_success`` triggers ``page.controls.clear()``
                # and the AutofillGroup is disposed — without it, the
                # Python-side mutation never reaches the mounted control
                # and disposal still fires with the initial CANCEL value.
                self._autofill_group.dispose_action = ft.AutofillGroupDisposeAction.COMMIT
                try:
                    self._autofill_group.update()
                except RuntimeError:
                    # Control isn't mounted (only happens in unit tests
                    # that don't attach this view to a real Page). Same
                    # pattern as ``_safe_update`` in views/dashboard.py.
                    pass

            self.on_login_success()

        except RequireMFAException:
            self._needs_mfa = True
            self.mfa_field.visible = True
            self.mfa_field.autofocus = True
            self.status_text.value = "MFA required. Enter your code below."
            self.status_text.color = ft.Colors.ON_SURFACE_VARIANT
            self.mfa_field.update()
            await self.mfa_field.focus()

        # Must precede LoginFailedException: CaptchaRequiredException
        # subclasses it, so the broader handler would otherwise catch it and
        # tell the user to check credentials that are almost certainly fine.
        except CaptchaRequiredException:
            self.status_text.value = CAPTCHA_STATUS_MESSAGE
            self.status_text.color = ft.Colors.ON_SURFACE_VARIANT
            # Nothing to retype, so focus stays put rather than being yanked
            # into the password field as it is for a real credential failure.

        except LoginFailedException:
            self.status_text.value = "Login failed. Check your credentials."
            self.status_text.color = ft.Colors.ERROR
            await self.password_field.focus()

        except Exception:
            logger.exception("Unexpected error during login")
            self.status_text.value = "Sign-in failed. Please try again."
            self.status_text.color = ft.Colors.ERROR

        finally:
            self.login_button.disabled = False
            self.login_text.value = "Sign In"
            self.progress.visible = False
            self.login_button.update()
            self.status_text.update()
