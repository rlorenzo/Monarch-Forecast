"""Manages Monarch Money authentication and session persistence."""

from pathlib import Path
from typing import Optional

import keyring
from monarchmoney import MonarchMoney

SERVICE_NAME = "monarch-forecast"
SESSION_DIR = Path.home() / ".monarch-forecast"
SESSION_FILE = SESSION_DIR / "session.pickle"


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

    def load_credentials(self) -> tuple[Optional[str], Optional[str]]:
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
        SESSION_FILE.chmod(0o600)
        self._authenticated = True

    async def login_with_mfa(self, email: str, password: str, mfa_code: str) -> None:
        """Login with email/password/MFA code."""
        await self._mm.multi_factor_authenticate(email, password, mfa_code)
        self._mm.save_session(str(SESSION_FILE))
        SESSION_FILE.chmod(0o600)
        self._authenticated = True

    def logout(self) -> None:
        self._authenticated = False
        self.clear_credentials()
        if SESSION_FILE.exists():
            SESSION_FILE.unlink()
