"""Tests for the update notification banner.

Cover the banner builder (correct copy + buttons), the Dismiss
``IconButton`` wired to flip visibility, and the Download button that
opens the release URL via ``webbrowser.open``.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import flet as ft

from src.views.update_banner import build_update_banner


def _m(obj: Any) -> Any:
    """Cast through ``Any`` so ``ty`` doesn't try to narrow stubbed Flet
    methods back to their declared shapes. The runtime calls are valid;
    the type info is stale.
    """
    return obj


def _walk(control: Any):
    if control is None:
        return
    yield control
    for attr in ("content", "controls", "actions", "title", "subtitle", "leading"):
        value = getattr(control, attr, None)
        if value is None:
            continue
        if isinstance(value, list):
            for child in value:
                yield from _walk(child)
        else:
            yield from _walk(value)


def _find_text_containing(control: Any, needle: str) -> bool:
    return any(isinstance(c, ft.Text) and c.value and needle in c.value for c in _walk(control))


def _find_text_button(control: Any, label: str) -> ft.TextButton | None:
    for c in _walk(control):
        if isinstance(c, ft.TextButton):
            # Flet 0.84 stashes the constructor's first arg in ``content``
            # — as a plain string for ``TextButton("Download")`` or as
            # ``ft.Text`` when the caller passes a styled instance.
            content = getattr(c, "content", None)
            if content == label:
                return c
            if isinstance(content, ft.Text) and content.value == label:
                return c
    return None


def _find_icon_button(control: Any, icon: Any) -> ft.IconButton | None:
    for c in _walk(control):
        if isinstance(c, ft.IconButton) and c.icon == icon:
            return c
    return None


class TestBannerCopy:
    def test_shows_new_version(self):
        banner = build_update_banner(
            {
                "version": "0.5.0",
                "download_url": "https://example.com/x.dmg",
                "html_url": "https://example.com/release",
            }
        )
        assert _find_text_containing(banner, "0.5.0")

    def test_shows_current_version(self):
        from src.utils.updater import get_current_version

        banner = build_update_banner(
            {
                "version": "0.5.0",
                "download_url": "",
                "html_url": "https://example.com/release",
            }
        )
        # Assert the body specifically calls out the running version
        # rather than just any "v" character (an upstream copy change
        # could otherwise pass the test by accident).
        assert _find_text_containing(banner, f"v{get_current_version()}")


class TestDownloadButton:
    def test_opens_download_url_when_present(self):
        banner = build_update_banner(
            {
                "version": "0.5.0",
                "download_url": "https://example.com/x.dmg",
                "html_url": "https://example.com/release",
            }
        )
        dl_btn = _find_text_button(banner, "Download")
        assert dl_btn is not None and dl_btn.on_click is not None
        with patch("src.views.update_banner.webbrowser.open") as mock_open:
            _m(dl_btn.on_click)(MagicMock())
            mock_open.assert_called_once_with("https://example.com/x.dmg")

    def test_falls_back_to_html_url(self):
        banner = build_update_banner(
            {
                "version": "0.5.0",
                "html_url": "https://example.com/release",
            }
        )
        dl_btn = _find_text_button(banner, "Download")
        assert dl_btn is not None and dl_btn.on_click is not None
        with patch("src.views.update_banner.webbrowser.open") as mock_open:
            _m(dl_btn.on_click)(MagicMock())
            mock_open.assert_called_once_with("https://example.com/release")

    def test_no_url_is_noop(self):
        banner = build_update_banner({"version": "0.5.0", "download_url": "", "html_url": ""})
        dl_btn = _find_text_button(banner, "Download")
        assert dl_btn is not None and dl_btn.on_click is not None
        with patch("src.views.update_banner.webbrowser.open") as mock_open:
            _m(dl_btn.on_click)(MagicMock())
            mock_open.assert_not_called()


class TestDismissButton:
    def test_dismiss_flips_visibility(self):
        banner = build_update_banner(
            {
                "version": "0.5.0",
                "download_url": "",
                "html_url": "https://example.com/release",
            }
        )
        dismiss = _find_icon_button(banner, ft.Icons.CLOSE)
        assert dismiss is not None and dismiss.on_click is not None
        # Stub ``update`` so the unmounted banner doesn't raise.
        setattr(banner, "update", MagicMock())  # noqa: B010
        _m(dismiss.on_click)(MagicMock())
        assert banner.visible is False
        _m(banner.update).assert_called_once()


class TestCheckUpdateAsync:
    async def test_runs_check_in_executor(self):
        # ``check_update_async`` delegates to ``check_for_update`` via a
        # thread executor. Patch ``check_for_update`` and assert the
        # async wrapper returns its value.
        from src.views.update_banner import check_update_async

        with patch("src.views.update_banner.check_for_update") as mock_check:
            mock_check.return_value = {"version": "0.5.0"}
            result = await check_update_async()
        assert result == {"version": "0.5.0"}
