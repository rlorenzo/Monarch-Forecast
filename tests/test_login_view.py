"""Tests for the LoginView async submit flow.

The view's ``_handle_login`` covers four user-facing paths:

1. Empty fields → inline error + focus moves to the empty field.
2. Successful login → ``on_login_success`` fires, credentials persisted
   when "Remember credentials" is checked.
3. ``RequireMFAException`` → MFA field becomes visible, status banner
   prompts for the code, second submit completes the login.
4. ``LoginFailedException`` / unexpected ``Exception`` → status text
   carries an error, button re-enables.

Each test mocks the session manager and stubs the controls' ``focus()``
+ ``update()`` so the handler can run without a mounted Flet page.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from monarchmoney import LoginFailedException, RequireMFAException

from src.auth.login_view import LoginView


def _m(obj: Any) -> Any:
    """Cast through ``Any`` so ``ty`` doesn't narrow the stubbed methods
    back to their Flet types. We've swapped ``focus`` / ``update`` /
    ``session_manager.login`` for ``Mock`` instances at runtime; ty can't
    see that, so every call site that wants ``.assert_called_once`` /
    ``.side_effect`` runs through this no-op.
    """
    return obj


def _stub_control_io(view: LoginView) -> None:
    """Replace ``update`` and ``focus`` on every interactive control so the
    handler can fire without being mounted to a Flet page.

    Without these stubs, ``Control.update()`` raises
    ``RuntimeError: ... must be added to the page first`` and
    ``Control.focus()`` is an async coroutine that requires a live
    session.
    """
    for control_name in (
        "email_field",
        "password_field",
        "mfa_field",
        "login_button",
        "login_text",
        "progress",
        "status_text",
    ):
        ctrl = getattr(view, control_name)
        ctrl.update = MagicMock()
        ctrl.focus = AsyncMock()


def _make_view(*, saved_email: str = "", saved_password: str = "") -> LoginView:
    sm = MagicMock()
    sm.load_credentials = MagicMock(return_value=(saved_email, saved_password))
    sm.login = AsyncMock()
    sm.login_with_mfa = AsyncMock()
    sm.save_credentials = MagicMock()
    view = LoginView(
        session_manager=sm,
        on_login_success=MagicMock(),
        on_demo=MagicMock(),
    )
    _stub_control_io(view)
    return view


def _event() -> Any:
    """A minimal stand-in for ``ft.Event[ft.Button]`` — the handler
    ignores it, but the signature demands a positional argument.
    """
    return MagicMock()


class TestConstruction:
    def test_prefills_saved_email(self):
        view = _make_view(saved_email="user@example.com")
        assert view.email_field.value == "user@example.com"

    def test_prefills_saved_password(self):
        view = _make_view(saved_email="u@e.com", saved_password="pw")
        assert view.password_field.value == "pw"

    def test_no_saved_credentials_leaves_fields_empty(self):
        view = _make_view()
        assert not view.email_field.value
        assert not view.password_field.value

    def test_remember_me_default_checked(self):
        view = _make_view()
        assert view.remember_me.value is True

    def test_demo_button_invokes_callback(self):
        view = _make_view()
        # Pull the demo button's on_click and trigger it.
        handler = view.demo_button.on_click
        assert handler is not None
        _m(handler)(_event())
        _m(view.on_demo).assert_called_once()


@pytest.mark.asyncio
class TestEmptyFields:
    async def test_empty_email_sets_status_and_focuses_email(self):
        view = _make_view()
        view.email_field.value = ""
        view.password_field.value = "secret"
        await view._handle_login(_event())
        assert "email and password" in (view.status_text.value or "")
        _m(view.email_field.focus).assert_awaited()

    async def test_empty_password_sets_status_and_focuses_password(self):
        view = _make_view()
        view.email_field.value = "user@example.com"
        view.password_field.value = ""
        await view._handle_login(_event())
        assert "email and password" in (view.status_text.value or "")
        _m(view.password_field.focus).assert_awaited()

    async def test_does_not_call_session_manager(self):
        view = _make_view()
        view.email_field.value = ""
        view.password_field.value = ""
        await view._handle_login(_event())
        _m(view.session_manager.login).assert_not_called()


@pytest.mark.asyncio
class TestSuccessfulLogin:
    async def test_login_invoked_with_credentials(self):
        view = _make_view()
        view.email_field.value = "user@example.com"
        view.password_field.value = "secret"
        await view._handle_login(_event())
        _m(view.session_manager.login).assert_awaited_with("user@example.com", "secret")

    async def test_credentials_saved_when_remember_me_checked(self):
        view = _make_view()
        view.email_field.value = "user@example.com"
        view.password_field.value = "secret"
        view.remember_me.value = True
        await view._handle_login(_event())
        _m(view.session_manager.save_credentials).assert_called_once_with(
            "user@example.com", "secret"
        )

    async def test_credentials_not_saved_when_remember_me_unchecked(self):
        view = _make_view()
        view.email_field.value = "user@example.com"
        view.password_field.value = "secret"
        view.remember_me.value = False
        await view._handle_login(_event())
        _m(view.session_manager.save_credentials).assert_not_called()

    async def test_on_login_success_fires(self):
        view = _make_view()
        view.email_field.value = "user@example.com"
        view.password_field.value = "secret"
        await view._handle_login(_event())
        _m(view.on_login_success).assert_called_once()

    async def test_strips_whitespace_from_credentials(self):
        view = _make_view()
        view.email_field.value = "  user@example.com  "
        view.password_field.value = "  secret  "
        await view._handle_login(_event())
        _m(view.session_manager.login).assert_awaited_with("user@example.com", "secret")


@pytest.mark.asyncio
class TestMFA:
    async def test_require_mfa_shows_mfa_field(self):
        view = _make_view()
        view.email_field.value = "user@example.com"
        view.password_field.value = "secret"
        _m(view.session_manager.login).side_effect = RequireMFAException()
        await view._handle_login(_event())
        assert view.mfa_field.visible is True
        assert view._needs_mfa is True
        assert "MFA required" in (view.status_text.value or "")

    async def test_mfa_resubmit_uses_login_with_mfa(self):
        view = _make_view()
        view.email_field.value = "user@example.com"
        view.password_field.value = "secret"
        _m(view.session_manager.login).side_effect = RequireMFAException()
        # First submit: trips MFA.
        await view._handle_login(_event())
        # Now enter the code and submit again.
        view.mfa_field.value = "123456"
        await view._handle_login(_event())
        _m(view.session_manager.login_with_mfa).assert_awaited_with(
            "user@example.com", "secret", "123456"
        )

    async def test_mfa_resubmit_with_empty_code_blocks(self):
        view = _make_view()
        view.email_field.value = "user@example.com"
        view.password_field.value = "secret"
        _m(view.session_manager.login).side_effect = RequireMFAException()
        await view._handle_login(_event())
        # Submit with empty MFA — should not call login_with_mfa.
        view.mfa_field.value = ""
        await view._handle_login(_event())
        _m(view.session_manager.login_with_mfa).assert_not_awaited()
        assert "MFA code" in (view.status_text.value or "")


@pytest.mark.asyncio
class TestErrors:
    async def test_login_failed_sets_status(self):
        view = _make_view()
        view.email_field.value = "user@example.com"
        view.password_field.value = "wrong"
        _m(view.session_manager.login).side_effect = LoginFailedException()
        await view._handle_login(_event())
        assert "credentials" in (view.status_text.value or "").lower()
        _m(view.password_field.focus).assert_awaited()
        # on_login_success should NOT fire on failed login.
        _m(view.on_login_success).assert_not_called()

    async def test_unexpected_exception_caught(self):
        view = _make_view()
        view.email_field.value = "user@example.com"
        view.password_field.value = "secret"
        _m(view.session_manager.login).side_effect = RuntimeError("boom")
        await view._handle_login(_event())
        # Generic copy, not propagating the raw exception.
        assert "Sign-in failed" in (view.status_text.value or "")
        _m(view.on_login_success).assert_not_called()

    async def test_button_re_enabled_after_error(self):
        view = _make_view()
        view.email_field.value = "user@example.com"
        view.password_field.value = "wrong"
        _m(view.session_manager.login).side_effect = LoginFailedException()
        await view._handle_login(_event())
        assert view.login_button.disabled is False
        assert view.progress.visible is False
        assert view.login_text.value == "Sign In"
