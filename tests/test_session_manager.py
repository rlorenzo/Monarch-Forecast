"""Tests for session manager (auth)."""

import sys
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

    @pytest.mark.skipif(sys.platform == "win32", reason="POSIX mode bits only")
    @patch("src.auth.session_manager.keyring")
    async def test_restore_refuses_world_writable_pickle(self, mock_keyring, tmp_session, tmp_path):
        """A session file with group/world-write bits must NOT be unpickled
        (defense against cross-user tampering; regression for PR #5)."""
        session_file = tmp_path / "session.pickle"
        session_file.write_bytes(b"fake")
        session_file.chmod(0o666)

        sm = SessionManager()
        load_session = MagicMock()
        cast(Any, sm._mm).load_session = load_session

        assert await sm.try_restore_session() is False
        assert sm.is_authenticated is False
        # Unsafe file is deleted so we don't keep tripping the check.
        assert not session_file.exists()
        # Crucially, load_session must never have been called on the
        # attacker-writable blob.
        load_session.assert_not_called()

    @pytest.mark.skipif(sys.platform == "win32", reason="POSIX mode bits only")
    @patch("src.auth.session_manager.keyring")
    async def test_restore_refuses_foreign_owned_pickle(
        self, mock_keyring, tmp_session, tmp_path, monkeypatch
    ):
        """A session file owned by a different uid must NOT be unpickled."""
        session_file = tmp_path / "session.pickle"
        session_file.write_bytes(b"fake")
        session_file.chmod(0o600)

        import os as _os

        real_uid = _os.getuid()
        monkeypatch.setattr("src.auth.session_manager.os.getuid", lambda: real_uid + 1)

        sm = SessionManager()
        load_session = MagicMock()
        cast(Any, sm._mm).load_session = load_session

        assert await sm.try_restore_session() is False
        load_session.assert_not_called()
        assert not session_file.exists()

    @pytest.mark.skipif(sys.platform == "win32", reason="POSIX symlinks")
    @patch("src.auth.session_manager.keyring")
    async def test_restore_refuses_symlink_pickle(self, mock_keyring, tmp_session, tmp_path):
        """Even a symlink owned by us must not be unpickled — it could
        point at attacker-controlled content."""
        real_target = tmp_path / "real.pickle"
        real_target.write_bytes(b"fake")
        session_file = tmp_path / "session.pickle"
        session_file.symlink_to(real_target)

        sm = SessionManager()
        load_session = MagicMock()
        cast(Any, sm._mm).load_session = load_session

        assert await sm.try_restore_session() is False
        load_session.assert_not_called()

    @patch("src.auth.session_manager.keyring")
    async def test_restore_refuses_directory_at_session_path(
        self, mock_keyring, tmp_session, tmp_path
    ):
        """If the path is a directory (not a regular file), the safety
        gate must fail-closed without calling load_session — unlink()
        can't remove a directory, so we must never reach it."""
        session_file = tmp_path / "session.pickle"
        session_file.mkdir(mode=0o700)

        sm = SessionManager()
        load_session = MagicMock()
        cast(Any, sm._mm).load_session = load_session

        assert await sm.try_restore_session() is False
        load_session.assert_not_called()
        # Directory should still exist — unlink() can't delete it, but the
        # OSError is swallowed so we don't crash the caller.
        assert session_file.is_dir()

    @pytest.mark.skipif(sys.platform == "win32", reason="POSIX symlinks")
    @patch("src.auth.session_manager.keyring")
    async def test_restore_removes_dangling_symlink(self, mock_keyring, tmp_session, tmp_path):
        """A dangling symlink at SESSION_FILE must be removed — not left
        in place for a subsequent save_session() to follow. Path.exists()
        returns False for dangling symlinks, so the safety gate has to
        run unconditionally."""
        session_file = tmp_path / "session.pickle"
        session_file.symlink_to(tmp_path / "does-not-exist")

        sm = SessionManager()
        load_session = MagicMock()
        cast(Any, sm._mm).load_session = load_session

        assert await sm.try_restore_session() is False
        load_session.assert_not_called()
        assert not session_file.is_symlink()
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

    @pytest.mark.skipif(sys.platform == "win32", reason="POSIX symlinks")
    @patch("src.auth.session_manager.keyring")
    async def test_login_clears_planted_symlink_before_save(
        self, mock_keyring, tmp_session, tmp_path
    ):
        """A symlink planted at SESSION_FILE (e.g. between logout and next
        login) must be removed before save_session — otherwise the pickle
        write would follow the symlink out of the intended directory."""
        target = tmp_path / "elsewhere.pickle"
        session_file = tmp_path / "session.pickle"
        session_file.symlink_to(target)

        sm = SessionManager()
        mm = cast(Any, sm._mm)
        mm.login = AsyncMock()
        mm.save_session = MagicMock()

        await sm.login("user@test.com", "pass")

        assert not session_file.is_symlink()
        assert not target.exists()
        mm.save_session.assert_called_once()

    @patch("src.auth.session_manager.keyring")
    def test_logout_survives_directory_at_session_path(self, mock_keyring, tmp_session, tmp_path):
        """If a directory is sitting at SESSION_FILE, unlink() raises
        IsADirectoryError. logout() must survive that — catching OSError,
        not just FileNotFoundError."""
        session_file = tmp_path / "session.pickle"
        session_file.mkdir()

        sm = SessionManager()
        sm.logout()  # must not raise
        assert session_file.is_dir()

    @pytest.mark.skipif(sys.platform == "win32", reason="POSIX uid")
    @patch("src.auth.session_manager.keyring")
    async def test_login_unlinks_foreign_owned_regular_file(
        self, mock_keyring, tmp_session, tmp_path, monkeypatch
    ):
        """An attacker-owned regular file at SESSION_FILE must be unlinked
        before save_session, so the next pickle write isn't captured by a
        file owned by another uid (who could pre-create it in a
        loosely-permissioned parent dir)."""
        import os as _os

        session_file = tmp_path / "session.pickle"
        session_file.write_bytes(b"attacker content")
        session_file.chmod(0o600)
        real_uid = _os.getuid()
        monkeypatch.setattr("src.auth.session_manager.os.getuid", lambda: real_uid + 1)

        sm = SessionManager()
        mm = cast(Any, sm._mm)
        mm.login = AsyncMock()

        def fake_save(path: str) -> None:
            with open(path, "wb") as f:
                f.write(b"our session")

        mm.save_session = MagicMock(side_effect=fake_save)

        await sm.login("user@test.com", "pass")

        assert session_file.read_bytes() == b"our session"
        mm.save_session.assert_called_once()

    @pytest.mark.skipif(sys.platform == "win32", reason="POSIX mode bits")
    @patch("src.auth.session_manager.keyring")
    async def test_login_unlinks_world_writable_regular_file(
        self, mock_keyring, tmp_session, tmp_path
    ):
        """Same class: a world-writable regular file is suspect even if
        we own it (any other process could write into it) — must be
        unlinked before save, so save_session produces a fresh 0o600
        file."""
        session_file = tmp_path / "session.pickle"
        session_file.write_bytes(b"suspect")
        session_file.chmod(0o666)

        sm = SessionManager()
        mm = cast(Any, sm._mm)
        mm.login = AsyncMock()

        def fake_save(path: str) -> None:
            with open(path, "wb") as f:
                f.write(b"fresh")

        mm.save_session = MagicMock(side_effect=fake_save)

        await sm.login("user@test.com", "pass")

        assert session_file.read_bytes() == b"fresh"
