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
        if not SESSION_FILE.exists():
            return False
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
        self._mm.save_session(str(SESSION_FILE))
        _chmod_session_file()
        self._authenticated = True

    async def login_with_mfa(self, email: str, password: str, mfa_code: str) -> None:
        """Login with email/password/MFA code."""
        await self._mm.multi_factor_authenticate(email, password, mfa_code)
        self._mm.save_session(str(SESSION_FILE))
        _chmod_session_file()
        self._authenticated = True

    def logout(self) -> None:
        self._authenticated = False
        self.clear_credentials()
        if SESSION_FILE.exists():
            SESSION_FILE.unlink()
