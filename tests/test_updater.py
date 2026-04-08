"""Tests for the auto-update checker."""

from typing import ClassVar

from src.utils.updater import _find_platform_asset, _is_newer


class TestIsNewer:
    def test_newer_patch(self):
        assert _is_newer("0.1.1", "0.1.0") is True

    def test_newer_minor(self):
        assert _is_newer("0.2.0", "0.1.0") is True

    def test_newer_major(self):
        assert _is_newer("1.0.0", "0.1.0") is True

    def test_same_version(self):
        assert _is_newer("0.1.0", "0.1.0") is False

    def test_older_version(self):
        assert _is_newer("0.0.9", "0.1.0") is False

    def test_invalid_latest(self):
        assert _is_newer("abc", "0.1.0") is False

    def test_empty_string(self):
        assert _is_newer("", "0.1.0") is False


class TestFindPlatformAsset:
    ASSETS: ClassVar[list[dict[str, str]]] = [
        {"name": "monarch-forecast-darwin.dmg", "browser_download_url": "https://example.com/mac"},
        {
            "name": "monarch-forecast-windows.msix",
            "browser_download_url": "https://example.com/win",
        },
        {
            "name": "monarch-forecast-linux.AppImage",
            "browser_download_url": "https://example.com/linux",
        },
    ]

    def test_macos(self, monkeypatch):
        monkeypatch.setattr("sys.platform", "darwin")
        assert _find_platform_asset(self.ASSETS) == "https://example.com/mac"

    def test_windows(self, monkeypatch):
        monkeypatch.setattr("sys.platform", "win32")
        assert _find_platform_asset(self.ASSETS) == "https://example.com/win"

    def test_linux(self, monkeypatch):
        monkeypatch.setattr("sys.platform", "linux")
        assert _find_platform_asset(self.ASSETS) == "https://example.com/linux"

    def test_no_matching_asset(self, monkeypatch):
        monkeypatch.setattr("sys.platform", "freebsd")
        assert _find_platform_asset(self.ASSETS) == ""

    def test_windows_does_not_match_darwin(self, monkeypatch):
        """Regression: 'win' substring should not match 'darwin' assets."""
        monkeypatch.setattr("sys.platform", "win32")
        assets = [
            {
                "name": "monarch-forecast-darwin.dmg",
                "browser_download_url": "https://example.com/mac",
            },
        ]
        assert _find_platform_asset(assets) == ""
