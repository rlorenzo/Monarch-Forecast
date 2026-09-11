"""Tests for "Erase local data" and the sign-out notice that pairs with it.

Two behaviours are pinned here:

1. Erase is *confirmed*, *complete*, and *survivable*. The dialog must not
   erase anything by itself, the handler must attempt every store even when
   one of them fails, and a failure must still sign the user out rather than
   trap them in a dashboard backed by data they asked to destroy.
2. Sign-out reports a cache it could not clear. The dashboard is torn down
   on the way to the login screen, so the only way the user ever hears
   about it is the notice handed to ``on_logout``.
"""

from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

import flet as ft
import pytest

from src.auth.login_view import LoginNotice, LoginView
from src.auth.session_manager import DemoSessionManager
from src.data import demo_data
from src.data.cache import DataCache
from src.data.preferences import Preferences
from src.views.dashboard import (
    CACHE_CLEAR_FAILED_NOTICE,
    ERASE_DONE_NOTICE,
    ERASE_FAILED_NOTICE,
    DashboardView,
)
from src.views.erase_data import ERASE_ITEMS, show_erase_data_dialog
from src.views.side_nav import NavDestination, SideNav

_ERASE_ROW_LABEL = "Erase local data from this computer"


def _walk(control: Any) -> list[Any]:
    """Flatten a Flet control tree into a list."""
    found: list[Any] = []
    stack = [control]
    while stack:
        node = stack.pop()
        if isinstance(node, list | tuple):
            stack.extend(node)
            continue
        if not isinstance(node, ft.BaseControl):
            continue
        found.append(node)
        for attr in ("controls", "content", "actions", "title"):
            child = getattr(node, attr, None)
            if child is not None:
                stack.append(child)
    return found


def _action_row_order(nav: SideNav) -> list[str]:
    """Accessible names of the rail's action rows, in laid-out order.

    ``_walk`` is depth-first over a stack and does not preserve sibling
    order, so ordering assertions read the column the rail actually
    assembled rather than the walk.
    """
    for node in _walk(nav):
        if not isinstance(node, ft.Column) or not node.controls:
            continue
        labels = [c.label for c in node.controls if isinstance(c, ft.Semantics) and c.label]
        if "Sign out" in labels:
            return labels
    raise AssertionError("no column holding the action rows")


def _dialog(page: MagicMock) -> ft.AlertDialog:
    dialog = page.show_dialog.call_args.args[0]
    assert isinstance(dialog, ft.AlertDialog)
    return dialog


@pytest.fixture
def page() -> MagicMock:
    page = MagicMock()
    page.show_dialog = MagicMock()
    page.pop_dialog = MagicMock()
    return page


class TestDialog:
    def test_opens_an_alert_dialog(self, page: MagicMock):
        show_erase_data_dialog(page, lambda: None)
        assert isinstance(_dialog(page), ft.AlertDialog)

    def test_names_every_store_it_will_erase(self, page: MagicMock):
        show_erase_data_dialog(page, lambda: None)
        rendered = " ".join(
            c.value for c in _walk(_dialog(page)) if isinstance(c, ft.Text) and c.value
        )
        for item in ERASE_ITEMS:
            assert item in rendered

    def test_warns_that_adjustments_go_too(self):
        """The one thing Sign out keeps and Erase does not — say so."""
        joined = " ".join(ERASE_ITEMS).lower()
        assert "override" in joined
        assert "one-off" in joined

    def test_cancel_takes_focus_not_erase(self, page: MagicMock):
        """Return must not be wired to the irreversible action."""
        show_erase_data_dialog(page, lambda: None)
        buttons = [c for c in _walk(_dialog(page).actions) if isinstance(c, ft.Button)]
        focused = [b for b in buttons if b.autofocus]
        assert len(focused) == 1
        assert focused[0].content == "Cancel"

    def test_cancel_closes_without_erasing(self, page: MagicMock):
        calls: list[int] = []
        show_erase_data_dialog(page, lambda: calls.append(1))
        cancel = next(
            b
            for b in _walk(_dialog(page).actions)
            if isinstance(b, ft.Button) and b.tooltip == "Cancel"
        )
        cancel.on_click(MagicMock())
        page.pop_dialog.assert_called_once()
        assert calls == []

    def test_erase_confirms_and_closes(self, page: MagicMock):
        calls: list[int] = []
        show_erase_data_dialog(page, lambda: calls.append(1))
        erase = next(
            b
            for b in _walk(_dialog(page).actions)
            if isinstance(b, ft.Button) and b.tooltip == "Erase everything"
        )
        erase.on_click(MagicMock())
        page.pop_dialog.assert_called_once()
        assert calls == [1]


class TestNavRailEntry:
    """The rail is the only way in, so it has to be wired."""

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
            on_erase_data=lambda: None,
            **kwargs,
        )

    def test_rail_has_an_erase_row(self):
        labels = [c.label for c in _walk(self._nav()) if isinstance(c, ft.Semantics)]
        assert _ERASE_ROW_LABEL in labels

    def test_erase_row_fires_the_callback(self):
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
            on_about=lambda: None,
            on_erase_data=lambda: calls.append(1),
        )
        row = next(
            c for c in _walk(nav) if isinstance(c, ft.Semantics) and c.label == _ERASE_ROW_LABEL
        )
        container = row.content
        assert isinstance(container, ft.Container)
        container.on_click(MagicMock())
        assert calls == [1]

    def test_erase_row_sits_below_sign_out(self):
        """Destructive last: it reads as the escalation of Sign out."""
        order = _action_row_order(self._nav())
        assert order.index(_ERASE_ROW_LABEL) > order.index("Sign out")


def _dash(patched_session_manager, tmp_path: Path, **kwargs: Any) -> DashboardView:
    return DashboardView(
        session_manager=patched_session_manager,
        cache=kwargs.pop("cache", None) or DataCache(db_path=tmp_path / "c.db"),
        preferences=kwargs.pop("preferences", None) or Preferences(path=tmp_path / "prefs.json"),
        **kwargs,
    )


class TestEraseHandler:
    def test_erases_cache_and_preferences_then_signs_out(
        self, patched_session_manager, tmp_path: Path
    ):
        cache = DataCache(db_path=tmp_path / "c.db")
        cache.set("txn_history:abc:750", [{"amount": 1.0}])
        prefs = Preferences(path=tmp_path / "prefs.json")
        prefs.set_onboarding_seen(True)
        on_logout = MagicMock()
        dash = _dash(
            patched_session_manager, tmp_path, on_logout=on_logout, cache=cache, preferences=prefs
        )

        dash._erase_local_data()

        assert not (tmp_path / "c.db").exists()
        assert not (tmp_path / "prefs.json").exists()
        assert Preferences(path=tmp_path / "prefs.json").onboarding_seen is False
        on_logout.assert_called_once_with(ERASE_DONE_NOTICE)

    def test_demo_leftovers_go_too(self, patched_session_manager, tmp_path: Path):
        """Demo files can hold adjustments the user typed while exploring.

        They sit in the same directory the real stores do, so leaving them
        behind would make "everything on this computer" untrue. The paths
        are redirected into ``tmp_path`` by the autouse ``_redirect_demo_paths``
        fixture in conftest.
        """
        demo_cache = demo_data.DEMO_CACHE_DB
        demo_prefs = demo_data.DEMO_PREFS_FILE
        demo_cache.write_bytes(b"demo")
        demo_prefs.write_text("{}")
        on_logout = MagicMock()
        dash = _dash(patched_session_manager, tmp_path, on_logout=on_logout)

        dash._erase_local_data()

        assert not demo_cache.exists()
        assert not demo_prefs.exists()
        on_logout.assert_called_once_with(ERASE_DONE_NOTICE)

    def test_demo_preferences_tmp_sidecar_goes_too(self, patched_session_manager, tmp_path: Path):
        """A crashed demo ``_save`` leaves a full copy in ``.json.tmp``.

        Erasing the visible file but not its sidecar would leave the
        adjustments the dialog promised to remove sitting on disk in
        readable JSON.
        """
        demo_data.DEMO_PREFS_FILE.write_text("{}")
        sidecar = demo_data.DEMO_PREFS_FILE.with_suffix(".json.tmp")
        sidecar.write_text('{"excluded_recurring": ["leftover"]}')
        dash = _dash(patched_session_manager, tmp_path, on_logout=MagicMock())

        dash._erase_local_data()

        assert not sidecar.exists()

    def test_absent_demo_leftovers_are_not_a_failure(self, patched_session_manager, tmp_path: Path):
        """Most users never open demo mode; that is the normal case.

        Nothing writes the redirected demo paths here, so they do not exist.
        """
        on_logout = MagicMock()
        dash = _dash(patched_session_manager, tmp_path, on_logout=on_logout)

        dash._erase_local_data()

        on_logout.assert_called_once_with(ERASE_DONE_NOTICE)

    def test_a_failing_store_does_not_strand_the_other(
        self, patched_session_manager, tmp_path: Path
    ):
        """One wedged file must not leave the rest of the data on disk."""
        cache = DataCache(db_path=tmp_path / "c.db")
        prefs = Preferences(path=tmp_path / "prefs.json")
        prefs.set_onboarding_seen(True)
        on_logout = MagicMock()
        dash = _dash(
            patched_session_manager, tmp_path, on_logout=on_logout, cache=cache, preferences=prefs
        )
        # Preferences is attempted first; make it blow up.
        dash._prefs.erase = MagicMock(side_effect=OSError("wedged"))  # type: ignore[method-assign]

        dash._erase_local_data()

        assert not (tmp_path / "c.db").exists()  # cache still erased
        on_logout.assert_called_once_with(ERASE_FAILED_NOTICE)

    def test_failure_still_signs_the_user_out(self, patched_session_manager, tmp_path: Path):
        on_logout = MagicMock()
        dash = _dash(patched_session_manager, tmp_path, on_logout=on_logout)
        dash._prefs.erase = MagicMock(side_effect=OSError)  # type: ignore[method-assign]
        dash._cache.erase = MagicMock(side_effect=OSError)  # type: ignore[method-assign]

        dash._erase_local_data()

        on_logout.assert_called_once_with(ERASE_FAILED_NOTICE)

    def test_a_preferences_file_that_will_not_unlink_is_reported(
        self, patched_session_manager, tmp_path: Path
    ):
        """The failure is injected beneath the real ``Preferences.erase``.

        ``Preferences.erase`` swallows its own OSErrors so one wedged file
        cannot abort the rest of an erase, which means a handler that only
        watched for exceptions would confirm a complete erase while the
        file sat there readable. Replacing the helper with a raising mock
        (as the tests above do) cannot catch that; patching ``Path.unlink``
        underneath it can.
        """
        prefs = Preferences(path=tmp_path / "prefs.json")
        prefs.set_onboarding_seen(True)
        on_logout = MagicMock()
        dash = _dash(patched_session_manager, tmp_path, on_logout=on_logout, preferences=prefs)

        with patch.object(Path, "unlink", side_effect=PermissionError("read-only")):
            dash._erase_local_data()

        assert (tmp_path / "prefs.json").exists()  # still there — and reported
        on_logout.assert_called_once_with(ERASE_FAILED_NOTICE)

    def test_a_cache_db_that_will_not_unlink_is_reported(
        self, patched_session_manager, tmp_path: Path
    ):
        """``DataCache.erase`` swallows unlink failures the same way."""
        cache = DataCache(db_path=tmp_path / "c.db")
        cache.set("txn_history:abc:750", [{"amount": 1.0}])
        on_logout = MagicMock()
        dash = _dash(patched_session_manager, tmp_path, on_logout=on_logout, cache=cache)
        with patch.object(Path, "unlink", side_effect=PermissionError("read-only")):
            dash._erase_local_data()

        assert (tmp_path / "c.db").exists()
        on_logout.assert_called_once_with(ERASE_FAILED_NOTICE)

    def test_a_failed_row_wipe_is_not_a_failure_if_the_file_goes(
        self, patched_session_manager, tmp_path: Path
    ):
        """Wiping the rows is the nice-to-have; removing the file is the point.

        A locked DB that refuses the DELETE still ends with cache.db gone,
        and the rows went with it — reporting failure there would train the
        user to ignore a notice that is supposed to mean something.
        """
        cache = DataCache(db_path=tmp_path / "c.db")
        cache.set("txn_history:abc:750", [{"amount": 1.0}])
        on_logout = MagicMock()
        dash = _dash(patched_session_manager, tmp_path, on_logout=on_logout, cache=cache)
        with patch.object(DataCache, "clear", side_effect=sqlite3.OperationalError("locked")):
            dash._erase_local_data()

        assert not (tmp_path / "c.db").exists()
        on_logout.assert_called_once_with(ERASE_DONE_NOTICE)

    def test_wedged_demo_leftovers_are_reported(self, patched_session_manager, tmp_path: Path):
        """Demo files can hold typed adjustments, so they count in the verdict."""
        demo_data.DEMO_CACHE_DB.write_bytes(b"demo")
        on_logout = MagicMock()
        dash = _dash(patched_session_manager, tmp_path, on_logout=on_logout)
        real_unlink = Path.unlink

        def refuse_demo_only(self: Path, *args: Any, **kwargs: Any) -> None:
            if self == demo_data.DEMO_CACHE_DB:
                raise PermissionError("read-only")
            real_unlink(self, *args, **kwargs)

        with patch.object(Path, "unlink", refuse_demo_only):
            dash._erase_local_data()

        assert demo_data.DEMO_CACHE_DB.exists()
        on_logout.assert_called_once_with(ERASE_FAILED_NOTICE)

    def test_nav_action_opens_the_erase_dialog(self, patched_session_manager, tmp_path: Path):
        """Specifically the erase dialog — asserting "an AlertDialog" would
        still pass if this opened About."""
        dash = _dash(patched_session_manager, tmp_path, on_logout=MagicMock())
        page = MagicMock(spec=ft.Page)
        with patch.object(ft.BaseControl, "page", new_callable=PropertyMock, return_value=page):
            dash._handle_erase_data()
        dialog = page.show_dialog.call_args[0][0]
        assert isinstance(dialog, ft.AlertDialog)
        rendered = " ".join(c.value for c in _walk(dialog) if isinstance(c, ft.Text) and c.value)
        assert "Erase local data?" in rendered
        assert ERASE_ITEMS[0] in rendered

    def test_the_rail_row_reaches_the_dialog(self, patched_session_manager, tmp_path: Path):
        """The rail is the only way in, so the callback has to be connected."""
        dash = _dash(patched_session_manager, tmp_path, on_logout=MagicMock())
        row = next(
            c
            for c in _walk(dash._nav_rail)
            if isinstance(c, ft.Semantics) and c.label == _ERASE_ROW_LABEL
        )
        container = row.content
        assert isinstance(container, ft.Container)
        page = MagicMock(spec=ft.Page)
        with (
            patch.object(ft.BaseControl, "page", new_callable=PropertyMock, return_value=page),
            patch("src.views.dashboard.show_erase_data_dialog") as mock_show,
        ):
            container.on_click(MagicMock())
        mock_show.assert_called_once()

    def test_demo_mode_does_not_offer_erase(self, tmp_path: Path):
        """A demo session has no credentials, session or real data to erase.

        Offering the action anyway would erase only the demo's own files
        while telling the user everything on the computer was gone.
        """
        dash = DashboardView(
            session_manager=DemoSessionManager(),
            on_logout=MagicMock(),
            raw_client=MagicMock(),
            cache=DataCache(db_path=tmp_path / "demo.db"),
            preferences=Preferences(path=tmp_path / "demo-prefs.json"),
        )
        labels = [c.label for c in _walk(dash._nav_rail) if isinstance(c, ft.Semantics)]
        assert _ERASE_ROW_LABEL not in labels
        assert "Sign out" in labels  # the rest of the rail is untouched


class TestEraseDemoDataIsBestEffort:
    """A wedged demo file must not abort the erase that is still to come.

    ``erase_demo_data`` runs last in the handler's loop, but the handler
    reports *which* stores failed — so these paths decide whether the user
    is told "erased" or "some data could not be erased", and getting them
    wrong reports a lie either way.
    """

    def test_a_cache_that_will_not_unlink_is_tolerated(self):
        with patch.object(Path, "unlink", side_effect=OSError("read-only")):
            assert demo_data.erase_demo_data() is False  # tolerated, not hidden

    def test_unreachable_preferences_are_tolerated(self, tmp_path: Path, monkeypatch):
        """A file planted where the demo directory should be.

        ``Preferences.__init__`` mkdirs its parent, which raises
        ``NotADirectoryError`` here — outside the OSError handling
        ``Preferences.erase`` does internally.
        """
        blocker = tmp_path / "blocker"
        blocker.write_text("not a directory")
        monkeypatch.setattr(demo_data, "DEMO_PREFS_FILE", blocker / "demo-preferences.json")

        assert demo_data.erase_demo_data() is False  # tolerated, not hidden

    def test_absent_files_report_success(self, tmp_path: Path):
        """The normal case: the user never opened demo mode.

        Nothing to delete is not a failed deletion — reporting otherwise
        would put a red "could not be erased" banner in front of nearly
        every user who erases.
        """
        assert demo_data.erase_demo_data() is True


class TestEraseDuringRefresh:
    """Erase can land while a refresh is suspended on a network call.

    The refresh task holds a reference to the dashboard and is not
    cancelled when the login view replaces it, so it resumes against a
    cache whose connection the erase has already closed.
    """

    async def test_a_resuming_refresh_does_not_raise(self, patched_session_manager, tmp_path: Path):
        cache = DataCache(db_path=tmp_path / "c.db")
        dash = _dash(patched_session_manager, tmp_path, on_logout=MagicMock(), cache=cache)
        started = asyncio.Event()
        release = asyncio.Event()

        async def slow_refresh(account_ids: list[str] | None = None) -> bool:
            started.set()
            await release.wait()
            return True

        dash._raw_client.refresh_accounts = AsyncMock(  # type: ignore[method-assign]
            side_effect=slow_refresh
        )
        task = asyncio.ensure_future(dash.monarch.refresh_accounts(["a"]))
        await started.wait()

        dash._erase_local_data()  # user confirms mid-refresh
        release.set()

        assert await task is True  # the bank sync still reports its result
        assert not (tmp_path / "c.db").exists()

    async def test_a_resuming_fetch_cannot_recreate_the_cache(
        self, patched_session_manager, tmp_path: Path
    ):
        """A cache miss normally writes the fetched accounts straight back."""
        db = tmp_path / "c.db"
        cache = DataCache(db_path=db)
        dash = _dash(patched_session_manager, tmp_path, on_logout=MagicMock(), cache=cache)
        dash._raw_client.get_checking_accounts = AsyncMock(  # type: ignore[method-assign]
            return_value=[{"id": "a", "displayName": "Everyday"}]
        )
        dash._erase_local_data()

        assert await dash.monarch.get_checking_accounts() == [
            {"id": "a", "displayName": "Everyday"}
        ]
        assert not db.exists()


class TestLogoutNotice:
    def test_clean_sign_out_carries_no_notice(self, patched_session_manager, tmp_path: Path):
        on_logout = MagicMock()
        dash = _dash(patched_session_manager, tmp_path, on_logout=on_logout)

        dash._handle_logout()

        on_logout.assert_called_once_with(None)

    def test_a_cache_that_will_not_clear_is_reported(self, patched_session_manager, tmp_path: Path):
        on_logout = MagicMock()
        dash = _dash(patched_session_manager, tmp_path, on_logout=on_logout)
        dash.monarch.clear_cache = MagicMock(  # type: ignore[method-assign]
            side_effect=OSError("locked")
        )

        dash._handle_logout()

        on_logout.assert_called_once_with(CACHE_CLEAR_FAILED_NOTICE)

    def test_sign_out_proceeds_even_when_the_cache_will_not_clear(
        self, patched_session_manager, tmp_path: Path
    ):
        """Refusing to sign the user out would be the worse failure."""
        on_logout = MagicMock()
        dash = _dash(patched_session_manager, tmp_path, on_logout=on_logout)
        dash.monarch.clear_cache = MagicMock(side_effect=OSError)  # type: ignore[method-assign]

        dash._handle_logout()

        assert on_logout.called


class TestNoticeReachesTheLoginScreen:
    """The dashboard is gone by then — the notice has to travel as data."""

    def test_login_view_renders_the_notice(self, patched_session_manager):
        notice = LoginNotice("Local data erased from this computer.", "#217547")
        view = LoginView(
            session_manager=patched_session_manager,
            on_login_success=lambda: None,
            on_demo=lambda: None,
            notice=notice,
        )
        assert view.status_text.value == notice.message
        assert view.status_text.color == notice.color

    def test_login_view_without_a_notice_is_blank(self, patched_session_manager):
        view = LoginView(
            session_manager=patched_session_manager,
            on_login_success=lambda: None,
            on_demo=lambda: None,
        )
        assert view.status_text.value == ""

    def test_the_notice_is_announced(self, patched_session_manager):
        """The status line is a live region, so notices are spoken."""
        view = LoginView(
            session_manager=patched_session_manager,
            on_login_success=lambda: None,
            on_demo=lambda: None,
            notice=LoginNotice("erased", "#217547"),
        )
        live = view._status_live_region
        assert isinstance(live, ft.Semantics)
        assert live.live_region is True
        assert view.status_text in _walk(live)
