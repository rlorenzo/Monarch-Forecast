"""Manages Monarch Money authentication and session persistence."""

import os
import stat
import sys
from pathlib import Path
from typing import ClassVar

import keyring
import keyring.errors
from monarchmoney import CaptchaRequiredException, LoginFailedException, MonarchMoney

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


def _credential_is_gone(key: str) -> bool:
    """Whether `key` reads back as absent from the keychain.

    Proof of absence, not a best guess: only a clean ``None`` counts. A
    value means the credential survived, and a read that fails means we
    cannot tell — both report "still there", because an erase that is
    unsure must not print "erased" over a live credential.
    """
    try:
        return keyring.get_password(SERVICE_NAME, key) is None
    except Exception:
        # Locked keychain, dead backend, anything else — no proof. Nothing
        # here may raise: logout() promises not to.
        return False


# HTTP statuses that mean the saved credential itself was refused. Every other
# failure — timeout, DNS, connection reset, 5xx — is about reaching Monarch,
# not about the token.
_AUTH_REJECTED_STATUSES = frozenset({401, 403})


def _is_credential_rejection(exc: BaseException) -> bool:
    """True only when Monarch definitively refused the saved credential.

    ``gql`` raises ``TransportServerError`` carrying a ``code`` for a non-200
    response. That attribute is read with ``getattr`` rather than by importing
    ``gql.transport.exceptions``: gql reaches us as a transitive of
    ``monarchmoneycommunity``, not as a dependency this project declares, so
    importing it here would be depending on someone else's dependency tree.

    ``LoginFailedException`` counts too: monarchmoney raises it when a call is
    attempted with no usable auth on the client. That says something about the
    credential rather than about the network, so no retry will fix it.

    ``CaptchaRequiredException`` is the trap in that rule. It *subclasses*
    ``LoginFailedException`` but means close to the opposite: Monarch is
    challenging the client, not refusing the token. monarchmoney raises it
    only from its login path today, so no restore currently reaches here
    carrying one — this branch guards the classifier's contract rather than
    fixing an observed failure. It earns its two lines because the failure it
    prevents is silent: the base-class branch would delete a live session and
    charge the user a full MFA re-login over a challenge a retry can clear.
    Order matters — the subclass has to be tested first.
    """
    if isinstance(exc, CaptchaRequiredException):
        return False
    if isinstance(exc, LoginFailedException):
        return True
    return getattr(exc, "code", None) in _AUTH_REJECTED_STATUSES


def _discard_session_file() -> bool:
    """Remove the session file, tolerating anything that isn't a file.

    Returns True when nothing is left at the path — a session file that
    was never written counts. The restore paths ignore the verdict (they
    are dropping a session they already know is unusable); ``logout()``
    uses it, because an "erase everything" that leaves a loadable session
    on disk must not report success.

    Deliberately not ``src.utils.files.erase_file``, which does the same
    thing for the cache and preferences: ``src.auth`` is a leaf module in
    tach.toml (``depends_on = []``) and importing a helper this small is
    not worth widening that boundary.
    """
    try:
        SESSION_FILE.unlink()
    except FileNotFoundError:
        return True
    except OSError:
        return False
    return True


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

    # Whether this session has credentials, a session file, and real cached
    # data of its own on this computer. Views read this instead of
    # type-testing the class, so a future session kind declares its own
    # answer here rather than being missed by an ``isinstance`` check in
    # some view that predates it.
    owns_local_data: ClassVar[bool] = True

    def __init__(self) -> None:
        SESSION_DIR.mkdir(parents=True, exist_ok=True, mode=0o700)
        # mode= on mkdir only applies when the directory is created; if it
        # already existed (e.g. from a looser umask on a prior run) it keeps
        # whatever perms it had. Tighten explicitly so we don't silently
        # leave a group/world-readable session directory.
        try:
            SESSION_DIR.chmod(0o700)
        except OSError:
            pass
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

    def clear_credentials(self) -> bool:
        """Drop the keychain entries, reporting whether they are all gone.

        Deleting an entry that was never saved is not a failure — a user who
        signed in without "remember me" has nothing to fail at — but the
        exception type alone cannot establish that is what happened.
        Absence is confirmed by reading the credential back; see
        `_credential_is_gone`.
        """
        cleared = True
        for key in ("email", "password"):
            try:
                keyring.delete_password(SERVICE_NAME, key)
            except keyring.errors.PasswordDeleteError:
                # Usually "nothing stored under this key", but not always:
                # the macOS backend wraps *every* Security API error in
                # PasswordDeleteError, KeychainDenied included, so a refusal
                # to delete a credential that is very much still there lands
                # here rather than in the KeyringError branch below. Only a
                # read-back tells the two apart.
                if not _credential_is_gone(key):
                    cleared = False
            except keyring.errors.KeyringError:
                # KeyringLocked, InitError and NoKeyringError are
                # PasswordDeleteError's siblings under KeyringError, and
                # they mean the opposite thing: the password may well still
                # be in the keychain. Still swallowed — raising out of
                # logout() would strand the user on a dashboard whose cache
                # and preferences an erase has already deleted — but
                # reported, so the erase does not claim to be complete.
                cleared = False
        return cleared

    async def try_restore_session(self) -> bool:
        """Attempt to restore a saved session. Returns True if successful.

        Returning False only means "could not restore now" — it does not mean
        the saved session is bad. The file is deleted solely when we can tell
        it will never work again; see `_is_credential_rejection`.
        """
        # Cleared up front so every failure path below can just `return False`
        # without each one having to remember to reset it.
        self._authenticated = False

        # No early `SESSION_FILE.exists()` check — it returns False for
        # dangling symlinks, which would skip the safety gate and leave a
        # planted symlink in place for a later `save_session()` to follow.
        # The safety gate handles missing files correctly (lstat → OSError
        # → False); unlink() below handles "not there" via OSError.
        if not _session_file_is_safe_to_load(SESSION_FILE):
            _discard_session_file()
            return False

        try:
            self._mm.load_session(str(SESSION_FILE))
        except Exception:
            # Unreadable, truncated, or not a session at all. This one cannot
            # improve on a retry, so drop it.
            _discard_session_file()
            return False

        try:
            # Validate the session is still good by making a lightweight call
            await self._mm.get_subscription_details()
        except Exception as exc:
            # Keep the session unless Monarch actually rejected it. A dropped
            # connection, a timeout, or a Monarch 5xx says nothing about
            # whether the token is still valid, and deleting on those costs
            # the user a full re-login *with MFA* the next time they launch —
            # a far worse outcome than retrying a token that turns out to be
            # dead, which costs one wasted request.
            if _is_credential_rejection(exc):
                _discard_session_file()
            return False

        self._authenticated = True
        return True

    async def login(self, email: str, password: str) -> None:
        """Login with email/password. Raises RequireMFAException if MFA needed."""
        # use_saved_session=False: the library default would pickle.load()
        # whatever sits at SESSION_FILE with none of the checks in
        # _session_file_is_safe_to_load(), and would silently ignore the
        # typed password in favour of a stale token.
        await self._mm.login(email=email, password=password, use_saved_session=False)
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

    def logout(self) -> bool:
        """Sign out, returning True when no credential or session remains.

        Never raises: _discard_session_file() swallows OSError (not just
        FileNotFoundError) so a planted directory at SESSION_FILE doesn't
        crash logout — unlink() can't remove dirs and raises
        IsADirectoryError — and clear_credentials() swallows keyring
        errors. Both report what they could not remove instead, because
        the erase path turns this into what the user is told.
        """
        self._authenticated = False
        # Both run before the verdict: a locked keychain must not skip the
        # session file, which is the half that keeps an account reachable.
        credentials_cleared = self.clear_credentials()
        session_discarded = _discard_session_file()
        return credentials_cleared and session_discarded


class DemoSessionManager(SessionManager):
    """Session manager for the login screen's "Try Demo Mode" button.

    Bypasses the real MonarchMoney client and keychain — all data comes from
    `src.data.demo_client.DemoClient`. The dashboard only reads `.client`
    when constructing its own MonarchClient, so demo mode must always pass
    its own `raw_client` override to DashboardView.
    """

    # No keychain entry, no session file, and only the throwaway ``demo-*``
    # files — so an "erase everything on this computer" action offered here
    # could not honour its own promise.
    owns_local_data: ClassVar[bool] = False

    def __init__(self) -> None:
        # Skip super().__init__ — no MonarchMoney, no keychain, no filesystem.
        self._mm = None  # type: ignore[assignment]
        self._authenticated = True

    def load_credentials(self) -> tuple[str | None, str | None]:
        return (DEMO_EMAIL, None)

    def logout(self) -> bool:
        # Nothing to remove: no keychain entry and no session file.
        return True

    async def try_restore_session(self) -> bool:
        return True
