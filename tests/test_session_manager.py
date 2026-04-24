"""Tests for session manager (auth)."""

from pathlib import Path
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.auth.session_manager import SessionManager


@pytest.fixture()
def tmp_session(tmp_path: Path, monkeypatch):
    """Redirect session storage to a temp directory."""
    monkeypatch.setattr("src.auth.session_manager.SESSION_DIR", tmp_path)
    monkeypatch.setattr("src.auth.session_manager.SESSION_FILE", tmp_path / "session.pickle")


class TestCredentials:
    @patch("src.auth.session_manager.keyring")
    def test_save_credentials(self, mock_keyring, tmp_session):
        sm = SessionManager()
        sm.save_credentials("user@test.com", "secret")
        assert mock_keyring.set_password.call_count == 2
        mock_keyring.set_password.assert_any_call("monarch-forecast", "email", "user@test.com")
        mock_keyring.set_password.assert_any_call("monarch-forecast", "password", "secret")

    @patch("src.auth.session_manager.keyring")
    def test_load_credentials(self, mock_keyring, tmp_session):
        mock_keyring.get_password.side_effect = lambda _svc, key: {
            "email": "user@test.com",
            "password": "secret",
        }.get(key)
        sm = SessionManager()
        email, password = sm.load_credentials()
        assert email == "user@test.com"
        assert password == "secret"

    @patch("src.auth.session_manager.keyring")
    def test_load_credentials_empty(self, mock_keyring, tmp_session):
        mock_keyring.get_password.return_value = None
        sm = SessionManager()
        email, password = sm.load_credentials()
        assert email is None
        assert password is None

    @patch("src.auth.session_manager.keyring")
    def test_clear_credentials(self, mock_keyring, tmp_session):
        sm = SessionManager()
        sm.clear_credentials()
        assert mock_keyring.delete_password.call_count == 2

    @patch("src.auth.session_manager.keyring")
    def test_clear_credentials_handles_missing(self, mock_keyring, tmp_session):
        import keyring.errors

        mock_keyring.delete_password.side_effect = keyring.errors.PasswordDeleteError()
        mock_keyring.errors = keyring.errors
        sm = SessionManager()
        sm.clear_credentials()  # should not raise


class TestSessionRestore:
    @patch("src.auth.session_manager.keyring")
    async def test_restore_no_session_file(self, mock_keyring, tmp_session):
        sm = SessionManager()
        assert await sm.try_restore_session() is False
        assert sm.is_authenticated is False

    @patch("src.auth.session_manager.keyring")
    async def test_restore_success(self, mock_keyring, tmp_session, tmp_path):
        # Create a fake session file
        session_file = tmp_path / "session.pickle"
        session_file.write_bytes(b"fake")

        sm = SessionManager()
        # Cast to Any so static type checkers don't trip on assigning
        # MagicMock/AsyncMock to methods typed as MonarchMoney methods.
        mm = cast(Any, sm._mm)
        mm.load_session = MagicMock()
        mm.get_subscription_details = AsyncMock(return_value={})

        assert await sm.try_restore_session() is True
        assert sm.is_authenticated is True

    @patch("src.auth.session_manager.keyring")
    async def test_restore_invalid_session(self, mock_keyring, tmp_session, tmp_path):
        session_file = tmp_path / "session.pickle"
        session_file.write_bytes(b"fake")

        sm = SessionManager()
        cast(Any, sm._mm).load_session = MagicMock(side_effect=Exception("bad session"))

        assert await sm.try_restore_session() is False
        assert sm.is_authenticated is False
        assert not session_file.exists()


class TestLogin:
    @patch("src.auth.session_manager.keyring")
    async def test_login_success(self, mock_keyring, tmp_session, tmp_path):
        session_file = tmp_path / "session.pickle"
        sm = SessionManager()
        mm = cast(Any, sm._mm)
        mm.login = AsyncMock()
        mm.save_session = MagicMock(side_effect=lambda _: session_file.write_bytes(b"s"))

        await sm.login("user@test.com", "pass")
        assert sm.is_authenticated is True
        mm.login.assert_awaited_once_with(email="user@test.com", password="pass")

    @patch("src.auth.session_manager.keyring")
    async def test_login_with_mfa(self, mock_keyring, tmp_session, tmp_path):
        session_file = tmp_path / "session.pickle"
        sm = SessionManager()
        mm = cast(Any, sm._mm)
        mm.multi_factor_authenticate = AsyncMock()
        mm.save_session = MagicMock(side_effect=lambda _: session_file.write_bytes(b"s"))

        await sm.login_with_mfa("user@test.com", "pass", "123456")
        assert sm.is_authenticated is True

    @patch("src.auth.session_manager.keyring")
    def test_logout(self, mock_keyring, tmp_session, tmp_path):
        session_file = tmp_path / "session.pickle"
        session_file.write_bytes(b"fake")

        sm = SessionManager()
        sm._authenticated = True
        sm.logout()

        assert sm.is_authenticated is False
        assert not session_file.exists()
