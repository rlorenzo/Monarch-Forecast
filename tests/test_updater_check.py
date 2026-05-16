"""Tests for ``check_for_update``: the HTTP-bound branches.

Mocks ``urllib.request.urlopen`` (via ``src.utils.updater.urlopen``) so
the test exercises the full request / parse / version-compare flow
without a network call.
"""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import MagicMock, patch
from urllib.error import URLError


def _patch_version(monkeypatch, version: str = "0.1.0", known: bool = True) -> None:
    """Override the module-level ``CURRENT_VERSION`` / ``_VERSION_KNOWN``
    so tests can simulate both the installed-package and run-from-source
    cases.
    """
    monkeypatch.setattr("src.utils.updater.CURRENT_VERSION", version)
    monkeypatch.setattr("src.utils.updater._VERSION_KNOWN", known)


def _mock_response(payload: dict[str, Any]) -> MagicMock:
    """Build an ``urlopen``-shaped context manager that yields a body
    matching ``payload``.
    """
    resp = MagicMock()
    resp.read.return_value = json.dumps(payload).encode("utf-8")
    cm = MagicMock()
    cm.__enter__.return_value = resp
    cm.__exit__.return_value = False
    return cm


class TestUpdateAvailable:
    def test_returns_dict_when_newer_version_published(self, monkeypatch):
        _patch_version(monkeypatch, "0.1.0")
        payload = {
            "tag_name": "v0.2.0",
            "body": "Release notes",
            "html_url": "https://github.com/owner/repo/releases/tag/v0.2.0",
            "assets": [
                {
                    "name": "monarch-forecast-darwin.dmg",
                    "browser_download_url": "https://example.com/mac",
                },
            ],
        }
        with patch("src.utils.updater.urlopen", return_value=_mock_response(payload)):
            monkeypatch.setattr("sys.platform", "darwin")
            from src.utils.updater import check_for_update

            result = check_for_update()
        assert result is not None
        assert result["version"] == "0.2.0"
        assert result["download_url"] == "https://example.com/mac"
        assert result["release_notes"] == "Release notes"

    def test_tag_without_v_prefix_still_works(self, monkeypatch):
        _patch_version(monkeypatch, "0.1.0")
        payload = {
            "tag_name": "0.5.0",  # no "v" prefix
            "body": "",
            "html_url": "https://example.com/release",
            "assets": [],
        }
        with patch("src.utils.updater.urlopen", return_value=_mock_response(payload)):
            from src.utils.updater import check_for_update

            result = check_for_update()
        assert result is not None
        assert result["version"] == "0.5.0"

    def test_falls_back_to_html_url_when_no_platform_asset(self, monkeypatch):
        _patch_version(monkeypatch, "0.1.0")
        payload = {
            "tag_name": "v0.2.0",
            "body": "",
            "html_url": "https://github.com/owner/repo/releases/tag/v0.2.0",
            "assets": [],
        }
        with patch("src.utils.updater.urlopen", return_value=_mock_response(payload)):
            from src.utils.updater import check_for_update

            result = check_for_update()
        assert result is not None
        assert result["download_url"] == "https://github.com/owner/repo/releases/tag/v0.2.0"


class TestNoUpdate:
    def test_returns_none_when_remote_same_version(self, monkeypatch):
        _patch_version(monkeypatch, "0.2.0")
        payload = {"tag_name": "v0.2.0", "assets": []}
        with patch("src.utils.updater.urlopen", return_value=_mock_response(payload)):
            from src.utils.updater import check_for_update

            assert check_for_update() is None

    def test_returns_none_when_remote_older(self, monkeypatch):
        _patch_version(monkeypatch, "0.3.0")
        payload = {"tag_name": "v0.2.0", "assets": []}
        with patch("src.utils.updater.urlopen", return_value=_mock_response(payload)):
            from src.utils.updater import check_for_update

            assert check_for_update() is None

    def test_returns_none_when_tag_empty(self, monkeypatch):
        _patch_version(monkeypatch, "0.1.0")
        payload = {"tag_name": "", "assets": []}
        with patch("src.utils.updater.urlopen", return_value=_mock_response(payload)):
            from src.utils.updater import check_for_update

            assert check_for_update() is None

    def test_returns_none_when_version_unknown(self, monkeypatch):
        # Simulates run-from-source mode (no installed metadata).
        _patch_version(monkeypatch, "0.0.0", known=False)
        with patch("src.utils.updater.urlopen") as mock_open:
            from src.utils.updater import check_for_update

            assert check_for_update() is None
            mock_open.assert_not_called()  # short-circuited; no HTTP request


class TestNetworkErrors:
    def test_url_error_returns_none(self, monkeypatch):
        _patch_version(monkeypatch, "0.1.0")
        with patch("src.utils.updater.urlopen", side_effect=URLError("dns")):
            from src.utils.updater import check_for_update

            assert check_for_update() is None

    def test_os_error_returns_none(self, monkeypatch):
        _patch_version(monkeypatch, "0.1.0")
        with patch("src.utils.updater.urlopen", side_effect=OSError("conn refused")):
            from src.utils.updater import check_for_update

            assert check_for_update() is None

    def test_invalid_json_returns_none(self, monkeypatch):
        _patch_version(monkeypatch, "0.1.0")
        resp = MagicMock()
        resp.read.return_value = b"not json"
        cm = MagicMock()
        cm.__enter__.return_value = resp
        cm.__exit__.return_value = False
        with patch("src.utils.updater.urlopen", return_value=cm):
            from src.utils.updater import check_for_update

            assert check_for_update() is None


class TestVersionShape:
    def test_get_current_version_returns_module_constant(self, monkeypatch):
        _patch_version(monkeypatch, "1.2.3")
        from src.utils.updater import get_current_version

        assert get_current_version() == "1.2.3"
