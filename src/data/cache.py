"""Simple SQLite cache for Monarch data to support offline/fast access."""

import json
import os
import sqlite3
import stat
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

CACHE_DIR = Path.home() / ".monarch-forecast"
CACHE_DB = CACHE_DIR / "cache.db"
DEFAULT_TTL_MINUTES = 30


class DataCache:
    """Key-value cache backed by SQLite with TTL expiration."""

    def __init__(self, db_path: Path = CACHE_DB) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        # Idempotent pre-create at 0o600 so there's no umask-default
        # window where sqlite3.connect() creates the file with loose
        # perms. Only run this path when O_NOFOLLOW is available: without
        # it, O_CREAT could in theory follow a planted symlink and
        # create/affect the target before the lstat gate below sees it.
        # On platforms without O_NOFOLLOW (effectively Windows), skip
        # the pre-create — we can't express "create without following
        # symlinks", and the umask-default window doesn't carry the same
        # meaning there (NTFS ACLs, not POSIX mode bits).
        # FileExistsError covers the pre-existing regular-file case
        # (legitimate prior run, or a race). Other OSErrors (EACCES,
        # ENOSPC, ELOOP from a symlink) propagate.
        if hasattr(os, "O_NOFOLLOW"):
            flags = os.O_CREAT | os.O_WRONLY | os.O_EXCL | os.O_NOFOLLOW
            try:
                fd = os.open(str(db_path), flags, 0o600)
                os.close(fd)
            except FileExistsError:
                pass
        # Authoritative validation immediately before sqlite3.connect —
        # closes the TOCTOU window where a symlink could be swapped in
        # between pre-create and connect. lstat() so a planted symlink
        # is seen as a symlink, not followed. On Windows (no pre-create)
        # the file may not exist yet — let sqlite3.connect create it.
        try:
            st = db_path.lstat()
        except FileNotFoundError:
            st = None
        if st is not None:
            if stat.S_ISLNK(st.st_mode) or not stat.S_ISREG(st.st_mode):
                raise OSError(f"refusing to use non-regular cache DB path: {db_path}")
            if sys.platform != "win32" and st.st_uid != os.getuid():
                raise OSError(f"refusing to use cache DB not owned by current uid: {db_path}")
        # Tighten perms BEFORE sqlite3.connect — a pre-existing 0o644 DB
        # would otherwise be read/written with loose perms in the window
        # before our chmod. For a just-pre-created file this is a no-op
        # (os.open already set 0o600). On platforms where we skipped the
        # pre-create (no O_NOFOLLOW) and the DB doesn't exist yet, this
        # chmod will FileNotFoundError — swallowed — and sqlite3.connect
        # below creates the file with umask defaults; the post-connect
        # chmod catches that case. chmod() semantics vary on Windows,
        # hence the broad except.
        try:
            db_path.chmod(0o600)
        except OSError:
            pass
        self._conn = sqlite3.connect(str(db_path))
        # Second chmod so a freshly-created-by-sqlite DB (the no-O_NOFOLLOW
        # first-run case) lands on 0o600 rather than whatever the umask
        # produced. No-op when the pre-connect chmod already succeeded.
        try:
            db_path.chmod(0o600)
        except OSError:
            pass
        self._conn.execute(
            """CREATE TABLE IF NOT EXISTS cache (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                expires_at TEXT NOT NULL
            )"""
        )
        self._conn.commit()

    def get(self, key: str) -> Any | None:
        row = self._conn.execute(
            "SELECT value, expires_at FROM cache WHERE key = ?", (key,)
        ).fetchone()
        if row is None:
            return None
        value, expires_at = row
        if datetime.fromisoformat(expires_at) < datetime.now():
            self._conn.execute("DELETE FROM cache WHERE key = ?", (key,))
            self._conn.commit()
            return None
        return json.loads(value)

    def set(self, key: str, value: Any, ttl_minutes: int = DEFAULT_TTL_MINUTES) -> None:
        expires_at = datetime.now() + timedelta(minutes=ttl_minutes)
        self._conn.execute(
            "INSERT OR REPLACE INTO cache (key, value, expires_at) VALUES (?, ?, ?)",
            (key, json.dumps(value), expires_at.isoformat()),
        )
        self._conn.commit()

    def clear(self) -> None:
        self._conn.execute("DELETE FROM cache")
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()
