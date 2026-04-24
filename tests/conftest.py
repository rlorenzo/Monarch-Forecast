"""Shared pytest fixtures."""

from pathlib import Path
from unittest.mock import patch

import pytest


@pytest.fixture
def patched_session_manager(tmp_path: Path, monkeypatch):
    """SessionManager with storage paths redirected and keyring stubbed.

    Covers the setup shared by UI tests that instantiate LoginView or
    DashboardView — both need a live SessionManager, both must not touch
    the real keychain or the user's ~/.monarch-forecast/ directory.
    """
    from src.auth.session_manager import SessionManager

    monkeypatch.setattr("src.auth.session_manager.SESSION_DIR", tmp_path)
    monkeypatch.setattr("src.auth.session_manager.SESSION_FILE", tmp_path / "s.pickle")
    monkeypatch.setattr("src.data.cache.CACHE_DB", tmp_path / "cache.db")

    with patch("src.auth.session_manager.keyring") as mock_keyring:
        mock_keyring.get_password.return_value = None
        yield SessionManager()
