"""Tests for the About dialog and the disclaimer it carries.

The disclaimer is a compliance surface, not decoration: it is the app's
only in-product statement that it is unaffiliated with Monarch Money and
talks to an unofficial API. These tests pin the claims themselves, so a
future copy edit that quietly drops one fails loudly.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, PropertyMock, patch

import flet as ft

from src.views.about import DISCLAIMER, MONARCH_URL, REPO_URL, _open_link, show_about_dialog
from src.views.dashboard import DashboardView
from src.views.side_nav import NavDestination, SideNav

REPO_ROOT = Path(__file__).resolve().parents[1]


def _paragraphs(markdown: str) -> list[str]:
    """Split markdown into paragraphs, normalising away line wrapping.

    README hard-wraps at ~72 columns and ``DISCLAIMER`` wraps wherever the
    string literal does, so the two are only comparable once whitespace
    inside a paragraph collapses to single spaces.
    """
    return [" ".join(block.split()) for block in markdown.split("\n\n") if block.strip()]


# The one paragraph README's Disclaimer section carries that the dialog
# does not: the pointer back into the app. Anything else appearing there
# means a claim was added to one surface and not the other.
_README_POINTER = (
    "The same text is shown in the app under **About** in the left nav; the "
    "`tests/test_about.py` suite fails if the two drift apart."
)


def _readme_disclaimer_section() -> str:
    """The body of README's ``## Disclaimer`` section."""
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    _, marker, after = readme.partition("## Disclaimer\n")
    assert marker, "README.md no longer has a '## Disclaimer' section"
    return after.split("\n## ")[0]


def _walk(root: Any):
    """Yield every control reachable from ``root`` (a control or a list of them)."""
    seen: set[int] = set()
    stack: list[Any] = list(root) if isinstance(root, list) else [root]
    while stack:
        c = stack.pop()
        if c is None or id(c) in seen:
            continue
        seen.add(id(c))
        yield c
        for attr in ("content", "controls", "actions", "title"):
            child = getattr(c, attr, None)
            if child is None:
                continue
            if isinstance(child, list):
                stack.extend(item for item in child if item is not None)
            else:
                stack.append(child)


def _shown_dialog() -> tuple[MagicMock, ft.AlertDialog]:
    page = MagicMock(spec=ft.Page)
    show_about_dialog(page)
    dialog = page.show_dialog.call_args[0][0]
    assert isinstance(dialog, ft.AlertDialog)
    return page, dialog


class TestDisclaimerText:
    """The three claims the disclaimer exists to make."""

    def test_states_no_affiliation(self):
        assert "not affiliated with Monarch Money" in DISCLAIMER

    def test_disclaims_endorsement_and_support(self):
        for word in ("endorsed", "sponsored", "supported"):
            assert word in DISCLAIMER

    def test_names_the_unofficial_api_and_the_terms(self):
        assert "no public API" in DISCLAIMER
        assert "reverse-engineered" in DISCLAIMER
        assert "terms of service" in DISCLAIMER

    def test_readme_repeats_the_disclaimer_verbatim(self):
        """README's Disclaimer section and the dialog must not drift apart.

        README tells the reader this test enforces that, so the check runs
        both ways: README's section must open with exactly the dialog's
        paragraphs, in order, and end with nothing but the pointer back to
        the app. A one-way "every app paragraph appears in README" check
        would pass after a paragraph was deleted from ``DISCLAIMER``, or
        after a fourth claim was added to README alone — both of which are
        exactly the drift README promises the suite rejects.
        """
        in_app = _paragraphs(DISCLAIMER)
        in_readme = _paragraphs(_readme_disclaimer_section())

        assert in_readme[: len(in_app)] == in_app, (
            "README's Disclaimer section no longer matches the dialog text in "
            "src/views/about.py. Update both, or the app and the README are "
            "making different promises about Monarch."
        )
        trailer = in_readme[len(in_app) :]
        assert trailer == [_README_POINTER], (
            f"README's Disclaimer section has unexpected extra content: {trailer}"
        )


class TestDialog:
    def test_shows_an_alert_dialog(self):
        _, dialog = _shown_dialog()
        titles = [c.value for c in _walk(dialog.title) if isinstance(c, ft.Text)]
        assert "About Monarch Forecast" in titles

    def test_body_renders_the_disclaimer(self):
        _, dialog = _shown_dialog()
        markdown = [c.value for c in _walk(dialog) if isinstance(c, ft.Markdown)]
        assert any(value == DISCLAIMER for value in markdown)

    def test_body_shows_version_and_licence(self):
        _, dialog = _shown_dialog()
        texts = [c.value or "" for c in _walk(dialog) if isinstance(c, ft.Text)]
        assert any(t.startswith("Version ") and "MIT licence" in t for t in texts)

    def test_close_action_pops_the_dialog(self):
        page, dialog = _shown_dialog()
        buttons = [
            c for c in _walk(dialog.actions) if isinstance(c, ft.Button) and c.on_click is not None
        ]
        assert buttons, "Close button should be clickable"
        buttons[0].on_click(MagicMock())
        page.pop_dialog.assert_called_once()

    def test_close_action_has_an_accessible_name(self):
        _, dialog = _shown_dialog()
        buttons = [c for c in _walk(dialog.actions) if isinstance(c, ft.Button)]
        assert any(b.content == "Close" for b in buttons)

    def test_close_action_takes_focus(self):
        """The dialog has no TextField, so Close must be what focus lands on."""
        _, dialog = _shown_dialog()
        buttons = [c for c in _walk(dialog.actions) if isinstance(c, ft.Button)]
        assert any(b.autofocus for b in buttons)


class TestLinkHandling:
    """``on_tap_link`` opens only the URLs this dialog renders."""

    def test_opens_allowed_urls(self):
        for url in (REPO_URL, MONARCH_URL):
            event = MagicMock()
            event.data = url
            with patch("src.views.about.webbrowser.open") as opener:
                _open_link(event)
            opener.assert_called_once_with(url)

    def test_ignores_anything_else(self):
        for url in ("https://evil.example.com", "file:///etc/passwd", ""):
            event = MagicMock()
            event.data = url
            with patch("src.views.about.webbrowser.open") as opener:
                _open_link(event)
            opener.assert_not_called()


class TestNavRailEntry:
    """The rail is the only way into the dialog, so it has to be wired."""

    def _nav(self, **kwargs: Any) -> SideNav:
        return SideNav(
            destinations=[
                NavDestination(
                    icon=ft.Icons.DASHBOARD_OUTLINED,
                    selected_icon=ft.Icons.DASHBOARD,
                    label="Overview",
                ),
            ],
            on_select=lambda _i: None,
            on_refresh=lambda: None,
            on_logout=lambda: None,
            on_about=lambda: None,
            **kwargs,
        )

    def test_rail_has_an_about_row(self):
        nav = self._nav()
        labels = [c.label for c in _walk(nav) if isinstance(c, ft.Semantics)]
        assert "About Monarch Forecast" in labels

    def test_about_row_fires_the_callback(self):
        calls: list[int] = []
        nav = SideNav(
            destinations=[
                NavDestination(
                    icon=ft.Icons.DASHBOARD_OUTLINED,
                    selected_icon=ft.Icons.DASHBOARD,
                    label="Overview",
                ),
            ],
            on_select=lambda _i: None,
            on_refresh=lambda: None,
            on_logout=lambda: None,
            on_about=lambda: calls.append(1),
        )
        row = next(
            c
            for c in _walk(nav)
            if isinstance(c, ft.Semantics) and c.label == "About Monarch Forecast"
        )
        container = row.content
        assert isinstance(container, ft.Container)
        assert container.on_click is not None
        container.on_click(MagicMock())
        assert calls == [1]


class TestDashboardWiring:
    """The rail's callback has to reach the dialog."""

    def test_handle_about_opens_the_dialog(self, patched_session_manager):
        dashboard = DashboardView(session_manager=patched_session_manager, on_logout=lambda: None)
        page = MagicMock(spec=ft.Page)
        with patch.object(ft.BaseControl, "page", new_callable=PropertyMock, return_value=page):
            dashboard._handle_about()
        dialog = page.show_dialog.call_args[0][0]
        assert isinstance(dialog, ft.AlertDialog)
