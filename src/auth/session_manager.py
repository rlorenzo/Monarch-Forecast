"""Manages Monarch Money authentication and session persistence."""

import os
import stat
import sys
from pathlib import Path

import keyring
import keyring.errors
from monarchmoney import MonarchMoney

SERVICE_NAME = "monarch-forecast"
SESSION_DIR = Path.home() / ".monarch-forecast"
SESSION_FILE = SESSION_DIR / "session.pickle"
DEMO_EMAIL = "demo@example.com"


def _session_file_is_safe_to_load(path: Path) -> bool:
    """Refuse to deserialize session pickle if filesystem metadata is loose.

    The MonarchMoney library uses pickle, so loading an attacker-writable file
    is RCE. This gate only defends against cross-user tampering: on POSIX we
    require the path to be a non-symlink regular file owned by the current
    uid and not group- or world-writable. It does NOT mitigate a malicious
    process running as the same user — that attacker can write a 0o600 file
    owned by the user that will pass this check. Removing pickle from the
    persistence format (or adding a keyring-backed HMAC over the blob) is the
    only real fix for that threat model. On Windows, mode bits don't reflect
    NTFS ACLs, so permission checks are skipped, but we still require a
    regular (non-symlink) file.
    """
    try:
        st = path.lstat()
    except OSError:
        return False
    if stat.S_ISLNK(st.st_mode):
        # Reject symlinks outright: a symlink owned by us could point at
        # an attacker-controlled pickle, and the mode bits on the link
        # itself aren't meaningful.
        return False
    if not stat.S_ISREG(st.st_mode):
        # Directories, FIFOs, sockets, devices — none of these can be
        # safely unpickled, and unlink() won't even clean up directories.
        return False
    if sys.platform == "win32":
        return True
    if st.st_uid != os.getuid():
        return False
    return not st.st_mode & 0o022


def _chmod_session_file() -> None:
    """Tighten session file perms to 0o600, tolerating non-POSIX filesystems."""
    try:
        SESSION_FILE.chmod(0o600)
    except OSError:
        pass


def _prepare_session_file_for_write() -> None:
    """Clear any unsafe existing file before save_session.

    MonarchMoney's save_session() writes through whatever is at the path,
    so a planted filesystem object there can redirect or expose the
    pickle. An existing regular file is kept only when it's safe: on
    POSIX, owned by the current uid and with no group or world
    permission bits set at all (mask 0o077) — otherwise another uid
    could pre-create the file or leave it group/world-readable before
    our next save writes secrets into it, and _chmod_session_file()'s
    0o600 tighten wouldn't close that read window in time. On Windows
    we accept any regular file because POSIX uid/mode bits don't map
    to NTFS ACLs. Anything else gets unlinked, and if unlink fails
    (e.g. a directory was planted) the OSError propagates and save
    fails closed.
    """
    try:
        st = SESSION_FILE.lstat()
    except FileNotFoundError:
        return
    if stat.S_ISREG(st.st_mode):
        if sys.platform == "win32":
            return
        # Reject any group/other perms (0o077), not just writable bits.
        # Otherwise a pre-existing 0o644 file (e.g. from a stale login
        # with a loose umask) leaves a world-readable window between
        # save_session() writing the pickle and _chmod_session_file()
        # tightening it. Safer to unlink + let save_session create a
        # fresh file that hits 0o600 immediately via our chmod.
        if st.st_uid == os.getuid() and not st.st_mode & 0o077:
            return
    SESSION_FILE.unlink()


class SessionManager:
    """Handles login, MFA, and session token persistence."""

    def __init__(self) -> None:
        SESSION_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._mm = MonarchMoney(session_file=str(SESSION_FILE))
        self._authenticated = False

    @property
    def client(self) -> MonarchMoney:
        return self._mm

    @property
    def is_authenticated(self) -> bool:
        return self._authenticated

    def save_credentials(self, email: str, password: str) -> None:
        keyring.set_password(SERVICE_NAME, "email", email)
        keyring.set_password(SERVICE_NAME, "password", password)

    def load_credentials(self) -> tuple[str | None, str | None]:
        email = keyring.get_password(SERVICE_NAME, "email")
        password = keyring.get_password(SERVICE_NAME, "password")
        return email, password

    def clear_credentials(self) -> None:
        for key in ("email", "password"):
            try:
                keyring.delete_password(SERVICE_NAME, key)
            except keyring.errors.PasswordDeleteError:
                pass

    async def try_restore_session(self) -> bool:
        """Attempt to restore a saved session. Returns True if successful."""
        # No early `SESSION_FILE.exists()` check — it returns False for
        # dangling symlinks, which would skip the safety gate and leave a
        # planted symlink in place for a later `save_session()` to follow.
        # The safety gate handles missing files correctly (lstat → OSError
        # → False); unlink() below handles "not there" via OSError.
        if not _session_file_is_safe_to_load(SESSION_FILE):
            try:
                SESSION_FILE.unlink()
            except OSError:
                pass
            return False
        try:
            self._mm.load_session(str(SESSION_FILE))
            # Validate the session is still good by making a lightweight call
            await self._mm.get_subscription_details()
            self._authenticated = True
            return True
        except Exception:
            self._authenticated = False
            if SESSION_FILE.exists():
                try:
                    SESSION_FILE.unlink()
                except OSError:
                    pass
            return False

    async def login(self, email: str, password: str) -> None:
        """Login with email/password. Raises RequireMFAException if MFA needed."""
        await self._mm.login(email=email, password=password)
        _prepare_session_file_for_write()
        self._mm.save_session(str(SESSION_FILE))
        _chmod_session_file()
        self._authenticated = True

    async def login_with_mfa(self, email: str, password: str, mfa_code: str) -> None:
        """Login with email/password/MFA code."""
        await self._mm.multi_factor_authenticate(email, password, mfa_code)
        _prepare_session_file_for_write()
        self._mm.save_session(str(SESSION_FILE))
        _chmod_session_file()
        self._authenticated = True

    def logout(self) -> None:
        self._authenticated = False
        self.clear_credentials()
        # Best-effort cleanup. Catching OSError (not just FileNotFoundError)
        # so a planted directory at SESSION_FILE doesn't crash logout —
        # unlink() can't remove dirs and raises IsADirectoryError.
        try:
            SESSION_FILE.unlink()
        except OSError:
            pass


class DemoSessionManager(SessionManager):
    """Session manager for the login screen's "Try Demo Mode" button.

    Bypasses the real MonarchMoney client and keychain — all data comes from
    `src.data.demo_client.DemoClient`. The dashboard only reads `.client`
    when constructing its own MonarchClient, so demo mode must always pass
    its own `raw_client` override to DashboardView.
    """

    def __init__(self) -> None:
        # Skip super().__init__ — no MonarchMoney, no keychain, no filesystem.
        self._mm = None  # type: ignore[assignment]
        self._authenticated = True

    def load_credentials(self) -> tuple[str | None, str | None]:
        return (DEMO_EMAIL, None)

    def logout(self) -> None:
        pass

    async def try_restore_session(self) -> bool:
        return True
