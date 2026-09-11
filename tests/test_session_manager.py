"""Tests for session manager (auth)."""

import sys
from pathlib import Path
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from monarchmoney import CaptchaRequiredException, LoginFailedException

from src.auth.session_manager import SessionManager, _is_credential_rejection


class _TransportServerError(Exception):
    """Stand-in for gql's ``TransportServerError``.

    Built locally rather than imported: ``gql`` is a transitive of
    ``monarchmoneycommunity``, and the production code classifies on the
    ``code`` attribute precisely so it need not import gql either. Anything
    carrying ``code`` is therefore the honest fixture — if the classifier ever
    starts demanding the real type, these tests should fail and say so.
    """

    def __init__(self, message: str, *, code: int) -> None:
        super().__init__(message)
        self.code = code


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
        # Read-back finds nothing, which is what makes this "never saved"
        # rather than "refused to delete".
        mock_keyring.get_password.return_value = None
        mock_keyring.errors = keyring.errors
        sm = SessionManager()
        # Nothing stored is not a failure: no credential is left either way,
        # so an erase built on this verdict can still say it is complete.
        assert sm.clear_credentials() is True

    @patch("src.auth.session_manager.keyring")
    def test_a_denied_delete_is_reported_even_as_passworddeleteerror(
        self, mock_keyring, tmp_session
    ):
        """PasswordDeleteError does not mean the credential was absent.

        keyring's macOS backend funnels every Security API error into
        PasswordDeleteError — KeychainDenied and SecAuthFailure included —
        so the "nothing was stored" branch would otherwise report success
        over a credential macOS simply refused to delete.
        """
        import keyring.errors

        mock_keyring.delete_password.side_effect = keyring.errors.PasswordDeleteError(
            "Can't delete password in keychain: KeychainDenied"
        )
        mock_keyring.get_password.return_value = "still-here"
        mock_keyring.errors = keyring.errors
        sm = SessionManager()
        assert sm.clear_credentials() is False
        assert mock_keyring.delete_password.call_count == 2

    @patch("src.auth.session_manager.keyring")
    def test_an_unverifiable_delete_is_reported_not_assumed_clear(self, mock_keyring, tmp_session):
        """If the read-back itself fails, absence is unproven, so: failure."""
        import keyring.errors

        mock_keyring.delete_password.side_effect = keyring.errors.PasswordDeleteError()
        mock_keyring.get_password.side_effect = keyring.errors.KeyringLocked()
        mock_keyring.errors = keyring.errors
        sm = SessionManager()
        assert sm.clear_credentials() is False

    @patch("src.auth.session_manager.keyring")
    def test_a_locked_keychain_is_reported_not_raised(self, mock_keyring, tmp_session):
        """A locked keychain may still be holding the password.

        Swallowed so logout() cannot strand the user on a dashboard whose
        cache and preferences an erase has already deleted, but reported —
        "erased" would otherwise be printed over a live credential.
        """
        import keyring.errors

        mock_keyring.delete_password.side_effect = keyring.errors.KeyringLocked()
        mock_keyring.errors = keyring.errors
        sm = SessionManager()
        assert sm.clear_credentials() is False
        # Both keys are still attempted — the first failure must not skip
        # whichever one the keychain might have given up.
        assert mock_keyring.delete_password.call_count == 2


class TestSessionDirPermissions:
    @pytest.mark.skipif(sys.platform == "win32", reason="POSIX mode bits only")
    @patch("src.auth.session_manager.keyring")
    def test_tightens_perms_on_preexisting_loose_dir(self, mock_keyring, tmp_session, tmp_path):
        """SESSION_DIR.mkdir(mode=0o700) only applies the mode on creation;
        if the directory already existed with looser perms (e.g. a stale
        run under a looser umask), the constructor must chmod it down to
        0o700 rather than leaving it as-is."""
        import stat as _stat

        tmp_path.chmod(0o755)

        SessionManager()

        mode = _stat.S_IMODE(tmp_path.stat().st_mode)
        assert mode == 0o700, f"expected 0o700, got {oct(mode)}"


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


class TestSessionSurvivesTransientFailures:
    """A failure to *reach* Monarch must not destroy a valid session.

    `try_restore_session` previously caught bare `Exception` and unlinked the
    session file on anything at all, so a dropped connection or a Monarch 5xx
    forced a full re-login with MFA on the next launch. The file is now removed
    only when Monarch actually refused the credential.
    """

    @staticmethod
    def _prepared(tmp_path: Path) -> tuple[SessionManager, Path]:
        session_file = tmp_path / "session.pickle"
        session_file.write_bytes(b"fake")
        sm = SessionManager()
        cast(Any, sm._mm).load_session = MagicMock()
        return sm, session_file

    @pytest.mark.parametrize(
        "exc",
        [
            pytest.param(OSError("connection reset"), id="connection-reset"),
            pytest.param(TimeoutError("timed out"), id="timeout"),
            pytest.param(_TransportServerError("server error", code=500), id="http-500"),
            pytest.param(_TransportServerError("bad gateway", code=502), id="http-502"),
            pytest.param(RuntimeError("something unexpected"), id="unexpected"),
        ],
    )
    @patch("src.auth.session_manager.keyring")
    async def test_transient_failure_keeps_the_session(
        self, mock_keyring, tmp_session, tmp_path, exc
    ):
        sm, session_file = self._prepared(tmp_path)
        cast(Any, sm._mm).get_subscription_details = AsyncMock(side_effect=exc)

        assert await sm.try_restore_session() is False
        assert sm.is_authenticated is False
        assert session_file.exists(), (
            f"{type(exc).__name__} says nothing about the token's validity, "
            "so the session must survive for the next launch"
        )

    @pytest.mark.parametrize(
        "exc",
        [
            pytest.param(_TransportServerError("unauthorized", code=401), id="http-401"),
            pytest.param(_TransportServerError("forbidden", code=403), id="http-403"),
            pytest.param(LoginFailedException("no usable auth"), id="login-failed"),
        ],
    )
    @patch("src.auth.session_manager.keyring")
    async def test_credential_rejection_discards_the_session(
        self, mock_keyring, tmp_session, tmp_path, exc
    ):
        sm, session_file = self._prepared(tmp_path)
        cast(Any, sm._mm).get_subscription_details = AsyncMock(side_effect=exc)

        assert await sm.try_restore_session() is False
        assert sm.is_authenticated is False
        assert not session_file.exists(), (
            "Monarch refused the credential, so keeping it would retry a token that can never work"
        )

    @patch("src.auth.session_manager.keyring")
    async def test_retained_session_restores_on_the_next_attempt(
        self, mock_keyring, tmp_session, tmp_path
    ):
        """The whole point of retaining the file: once the network comes back,
        the very next restore succeeds with no re-login and no MFA prompt."""
        sm, _ = self._prepared(tmp_path)
        mm = cast(Any, sm._mm)
        mm.get_subscription_details = AsyncMock(side_effect=OSError("connection reset"))

        assert await sm.try_restore_session() is False

        mm.get_subscription_details = AsyncMock(return_value={})

        assert await sm.try_restore_session() is True
        assert sm.is_authenticated is True


class TestCredentialRejectionClassifier:
    """Direct tests for the classifier rule the restore flow cannot exercise.

    Every other rule in ``_is_credential_rejection`` is covered end-to-end
    above. The captcha rule can't be: monarchmoney raises
    ``CaptchaRequiredException`` only from its login path, never from the
    session-validating call ``try_restore_session`` makes, so routing it
    through the restore flow would mean mocking a failure the library cannot
    produce there. Asserted at the classifier instead, where it is real.
    """

    def test_captcha_is_not_a_credential_rejection(self):
        """``CaptchaRequiredException`` subclasses ``LoginFailedException``,
        which the classifier does treat as a rejection, but it means the
        opposite: Monarch challenging the client, not refusing the token.
        Reversing the two checks would silently discard a live session and
        cost the user a full MFA re-login.
        """
        assert _is_credential_rejection(CaptchaRequiredException("captcha required")) is False
        assert _is_credential_rejection(LoginFailedException("no usable auth")) is True


class TestSessionRestoreSafetyGate:
    """The pre-unpickle checks on SESSION_FILE, split out from restore
    behaviour because these fail before load_session is ever reached."""

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

    @patch("src.auth.session_manager.keyring")
    async def test_failed_gate_clears_stale_authenticated_state(
        self, mock_keyring, tmp_session, tmp_path
    ):
        """A restore that fails the gate must leave the manager unauthenticated
        even if an earlier restore had already set the flag."""
        session_file = tmp_path / "session.pickle"
        session_file.mkdir(mode=0o700)

        sm = SessionManager()
        sm._authenticated = True
        cast(Any, sm._mm).load_session = MagicMock()

        assert await sm.try_restore_session() is False
        assert sm.is_authenticated is False


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
        mm.login.assert_awaited_once_with(
            email="user@test.com", password="pass", use_saved_session=False
        )

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

        assert sm.logout() is True
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
        assert sm.logout() is False  # must not raise, but must not lie either
        assert session_file.is_dir()

    @patch("src.auth.session_manager.keyring")
    def test_logout_clears_the_session_even_when_the_keychain_is_locked(
        self, mock_keyring, tmp_session, tmp_path
    ):
        """The session file is the half that keeps the account reachable.

        A keyring failure must not short-circuit past it — and the verdict
        still has to come back False, because the password may remain.
        """
        import keyring.errors

        mock_keyring.delete_password.side_effect = keyring.errors.KeyringLocked()
        mock_keyring.errors = keyring.errors
        session_file = tmp_path / "session.pickle"
        session_file.write_bytes(b"fake")

        sm = SessionManager()

        assert sm.logout() is False
        assert not session_file.exists()

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
