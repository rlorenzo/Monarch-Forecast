"""Tests for ``DashboardView`` dialog flows.

Three dialogs surface from the dashboard:

1. ``_maybe_show_onboarding`` — first-launch welcome with a Got-it
   button that persists the seen-flag.
2. ``_show_threshold_help`` — modal explaining the Safety Threshold,
   dismissable with a Got it button.
3. ``_show_unsaved_cc_dialog`` and its refresh-variant — guard against
   navigating or refreshing with pending CC billing edits. Three
   action buttons: Save all, Discard, Cancel. Save-all delegates to
   each dirty card's ``save`` closure.

All three reach for ``self.page.show_dialog``; tests run them with
``ft.BaseControl.page`` patched to a MagicMock.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, PropertyMock, patch

import flet as ft
import pytest

from src.data.preferences import Preferences
from src.views.dashboard import DashboardView


def _m(obj: Any) -> Any:
    return obj


@pytest.fixture
def fake_page() -> MagicMock:
    page = MagicMock(spec=ft.Page)
    page.show_dialog = MagicMock()
    page.pop_dialog = MagicMock()
    page.run_task = MagicMock()
    return page


@pytest.fixture
def dashboard(patched_session_manager, tmp_path: Path):
    prefs = Preferences(path=tmp_path / "prefs.json")
    dash = DashboardView(
        session_manager=patched_session_manager,
        on_logout=MagicMock(),
        preferences=prefs,
    )
    setattr(dash, "_run_task", MagicMock())  # noqa: B010
    setattr(dash, "_show_snackbar", MagicMock())  # noqa: B010
    return dash


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


def _find_text_button(dialog: Any, label: str) -> ft.TextButton | None:
    for c in _walk(dialog):
        if isinstance(c, ft.TextButton):
            content = getattr(c, "content", None)
            if content == label:
                return c
            if isinstance(content, ft.Text) and content.value == label:
                return c
    return None


def _find_filled_button(dialog: Any, label: str) -> ft.FilledButton | None:
    for c in _walk(dialog):
        if isinstance(c, ft.FilledButton):
            content = getattr(c, "content", None)
            if content == label:
                return c
            if isinstance(content, ft.Text) and content.value == label:
                return c
    return None


def _find_semantics_button(dialog: Any, label: str) -> ft.Container | None:
    """The Got-it style buttons are coral/ink Containers wrapped in
    ``ft.Semantics(label=...)``. Return the clickable Container."""
    for c in _walk(dialog):
        if isinstance(c, ft.Semantics) and c.label == label:
            inner = c.content
            if isinstance(inner, ft.Container) and inner.on_click is not None:
                return inner
    return None


def _with_mock_page(page: MagicMock):
    return patch.object(ft.BaseControl, "page", new_callable=PropertyMock, return_value=page)


# ---------------------------------------------------------------------------
# Onboarding
# ---------------------------------------------------------------------------


class TestOnboardingDialog:
    def test_first_launch_shows_dialog(self, dashboard, fake_page):
        # onboarding_seen defaults to False on a fresh prefs file.
        assert dashboard._prefs.onboarding_seen is False
        with _with_mock_page(fake_page):
            dashboard._maybe_show_onboarding()
        fake_page.show_dialog.assert_called_once()

    def test_subsequent_launch_skips(self, dashboard, fake_page):
        dashboard._prefs.set_onboarding_seen(True)
        with _with_mock_page(fake_page):
            dashboard._maybe_show_onboarding()
        fake_page.show_dialog.assert_not_called()

    def test_got_it_button_persists_seen_flag(self, dashboard, fake_page):
        assert dashboard._prefs.onboarding_seen is False
        with _with_mock_page(fake_page):
            dashboard._maybe_show_onboarding()
        dialog = fake_page.show_dialog.call_args[0][0]
        # Dialog actions are ``[TextButton("Got it!", ...)]``.
        got_it = _find_text_button(dialog, "Got it!")
        assert got_it is not None and got_it.on_click is not None
        with _with_mock_page(fake_page):
            _m(got_it.on_click)(MagicMock())
        assert dashboard._prefs.onboarding_seen is True
        fake_page.pop_dialog.assert_called_once()


# ---------------------------------------------------------------------------
# Threshold help
# ---------------------------------------------------------------------------


class TestThresholdHelpDialog:
    def test_opens_dialog(self, dashboard, fake_page):
        with _with_mock_page(fake_page):
            dashboard._show_threshold_help()
        fake_page.show_dialog.assert_called_once()

    def test_got_it_dismisses(self, dashboard, fake_page):
        with _with_mock_page(fake_page):
            dashboard._show_threshold_help()
        dialog = fake_page.show_dialog.call_args[0][0]
        # Got-it is the dashboard's editorial Container-button (Semantics
        # wrapper labeled "Got it").
        btn = _find_semantics_button(dialog, "Got it")
        assert btn is not None and btn.on_click is not None
        with _with_mock_page(fake_page):
            _m(btn.on_click)(MagicMock())
        fake_page.pop_dialog.assert_called_once()


# ---------------------------------------------------------------------------
# Unsaved CC dialog (tab-switch path)
# ---------------------------------------------------------------------------


def _seed_dirty_card(
    dashboard: DashboardView,
    cc_id: str = "cc1",
    name: str = "Chase",
    save_returns: bool = True,
) -> MagicMock:
    """Register a dirty CC card. ``save_returns`` controls whether the
    save closure reports success or validation failure.
    """
    save_fn = MagicMock(return_value=save_returns)
    indicator = MagicMock()
    indicator.visible = True
    dashboard._dirty_cc_cards[cc_id] = {
        "save": save_fn,
        "indicator": indicator,
        "name": name,
    }
    return save_fn


class TestUnsavedCCDialog:
    def test_single_card_message(self, dashboard, fake_page):
        _seed_dirty_card(dashboard, name="Chase Sapphire")
        with _with_mock_page(fake_page):
            dashboard._pending_nav_target = 1
            dashboard._show_unsaved_cc_dialog()
        dialog = fake_page.show_dialog.call_args[0][0]
        # Dialog content is a Text — verify body mentions the card name.
        body = next(
            c
            for c in _walk(dialog)
            if isinstance(c, ft.Text) and "Chase Sapphire" in (c.value or "")
        )
        assert "Chase Sapphire" in body.value

    def test_multiple_cards_message(self, dashboard, fake_page):
        _seed_dirty_card(dashboard, "cc1", name="Chase")
        _seed_dirty_card(dashboard, "cc2", name="Amex")
        with _with_mock_page(fake_page):
            dashboard._pending_nav_target = 1
            dashboard._show_unsaved_cc_dialog()
        dialog = fake_page.show_dialog.call_args[0][0]
        body = next(
            c for c in _walk(dialog) if isinstance(c, ft.Text) and "credit cards" in (c.value or "")
        )
        assert "Chase" in body.value
        assert "Amex" in body.value
        assert "2" in body.value  # count

    def test_save_all_success_proceeds_to_target(self, dashboard, fake_page):
        save_fn = _seed_dirty_card(dashboard)
        dashboard._pending_nav_target = 2
        with _with_mock_page(fake_page):
            dashboard._show_unsaved_cc_dialog()
            dialog = fake_page.show_dialog.call_args[0][0]
            save_all = _find_filled_button(dialog, "Save all")
            assert save_all is not None
            _m(save_all.on_click)(MagicMock())
        save_fn.assert_called_once_with(False)  # show_success=False
        _m(dashboard._show_snackbar).assert_called()
        # Navigation proceeded — current index == target, pending cleared.
        assert dashboard._current_nav_index == 2
        assert dashboard._pending_nav_target is None

    def test_save_all_validation_failure_stays_put(self, dashboard, fake_page):
        save_fn = _seed_dirty_card(dashboard, save_returns=False)
        dashboard._pending_nav_target = 1
        prior_index = dashboard._current_nav_index
        with _with_mock_page(fake_page):
            dashboard._show_unsaved_cc_dialog()
            dialog = fake_page.show_dialog.call_args[0][0]
            save_all = _find_filled_button(dialog, "Save all")
            assert save_all is not None
            _m(save_all.on_click)(MagicMock())
        save_fn.assert_called_once_with(False)
        # Validation failed — nav blocked.
        assert dashboard._current_nav_index == prior_index

    def test_discard_clears_dirty_and_proceeds(self, dashboard, fake_page):
        _seed_dirty_card(dashboard)
        dashboard._pending_nav_target = 2
        with _with_mock_page(fake_page):
            dashboard._show_unsaved_cc_dialog()
            dialog = fake_page.show_dialog.call_args[0][0]
            discard = _find_text_button(dialog, "Discard")
            assert discard is not None
            _m(discard.on_click)(MagicMock())
        assert dashboard._dirty_cc_cards == {}
        assert dashboard._current_nav_index == 2

    def test_cancel_rolls_back_pending(self, dashboard, fake_page):
        _seed_dirty_card(dashboard)
        dashboard._pending_nav_target = 2
        with _with_mock_page(fake_page):
            dashboard._show_unsaved_cc_dialog()
            dialog = fake_page.show_dialog.call_args[0][0]
            cancel = _find_text_button(dialog, "Cancel")
            assert cancel is not None
            _m(cancel.on_click)(MagicMock())
        assert dashboard._pending_nav_target is None
        # Dirty card stays — user hasn't decided yet.
        assert "cc1" in dashboard._dirty_cc_cards


# ---------------------------------------------------------------------------
# Unsaved CC dialog (refresh path)
# ---------------------------------------------------------------------------


class TestUnsavedCCRefreshDialog:
    def test_save_all_then_refresh(self, dashboard, fake_page):
        save_fn = _seed_dirty_card(dashboard)
        with _with_mock_page(fake_page):
            dashboard._show_unsaved_cc_dialog_for_refresh()
            dialog = fake_page.show_dialog.call_args[0][0]
            save_btn = _find_filled_button(dialog, "Save & refresh")
            assert save_btn is not None
            _m(save_btn.on_click)(MagicMock())
        save_fn.assert_called_once_with(False)
        # _run_task scheduled the refresh action.
        _m(dashboard._run_task).assert_called_with(dashboard._on_refresh_action)

    def test_save_validation_failure_does_not_refresh(self, dashboard, fake_page):
        _seed_dirty_card(dashboard, save_returns=False)
        with _with_mock_page(fake_page):
            dashboard._show_unsaved_cc_dialog_for_refresh()
            dialog = fake_page.show_dialog.call_args[0][0]
            save_btn = _find_filled_button(dialog, "Save & refresh")
            assert save_btn is not None
            _m(save_btn.on_click)(MagicMock())
        _m(dashboard._run_task).assert_not_called()

    def test_discard_then_refresh(self, dashboard, fake_page):
        _seed_dirty_card(dashboard)
        with _with_mock_page(fake_page):
            dashboard._show_unsaved_cc_dialog_for_refresh()
            dialog = fake_page.show_dialog.call_args[0][0]
            discard = _find_text_button(dialog, "Discard & refresh")
            assert discard is not None
            _m(discard.on_click)(MagicMock())
        assert dashboard._dirty_cc_cards == {}
        _m(dashboard._run_task).assert_called_with(dashboard._on_refresh_action)

    def test_cancel_does_nothing(self, dashboard, fake_page):
        _seed_dirty_card(dashboard)
        with _with_mock_page(fake_page):
            dashboard._show_unsaved_cc_dialog_for_refresh()
            dialog = fake_page.show_dialog.call_args[0][0]
            cancel = _find_text_button(dialog, "Cancel")
            assert cancel is not None
            _m(cancel.on_click)(MagicMock())
        # Dirty card preserved, no refresh.
        assert "cc1" in dashboard._dirty_cc_cards
        _m(dashboard._run_task).assert_not_called()
