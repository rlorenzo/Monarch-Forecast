"""Unit tests for the editorial left-hand nav (SideNav).

Focused on the component's state machine and public API. Visual rendering
is exercised by ``tests/test_views_smoke.py`` (via DashboardView) and by
the accessibility regression suite in ``tests/test_accessibility.py``.
"""

from __future__ import annotations

import flet as ft

from src.views import tokens
from src.views.side_nav import NavDestination, SideNav


def _destinations() -> list[NavDestination]:
    return [
        NavDestination(
            icon=ft.Icons.DASHBOARD_OUTLINED,
            selected_icon=ft.Icons.DASHBOARD,
            label="Overview",
        ),
        NavDestination(
            icon=ft.Icons.TABLE_CHART_OUTLINED,
            selected_icon=ft.Icons.TABLE_CHART,
            label="Transactions",
        ),
        NavDestination(
            icon=ft.Icons.TUNE_OUTLINED,
            selected_icon=ft.Icons.TUNE,
            label="Adjustments",
        ),
    ]


def _make(
    *,
    on_select=lambda _idx: None,
    on_refresh=lambda: None,
    on_logout=lambda: None,
    user_email: str = "",
) -> SideNav:
    return SideNav(
        destinations=_destinations(),
        on_select=on_select,
        on_refresh=on_refresh,
        on_logout=on_logout,
        user_email=user_email,
    )


class TestSelectedIndex:
    """Programmatic selection drives the active paint without firing on_select."""

    def test_initial_index_is_zero(self):
        nav = _make()
        assert nav.selected_index == 0

    def test_setter_updates_active_paint(self):
        nav = _make()
        # Overview starts active
        assert nav._dest_parts[0].rail.bgcolor == tokens.CORAL
        assert nav._dest_parts[1].rail.bgcolor == "transparent"

        nav.selected_index = 1

        assert nav.selected_index == 1
        assert nav._dest_parts[0].rail.bgcolor == "transparent"
        assert nav._dest_parts[1].rail.bgcolor == tokens.CORAL
        # Icon swaps to its filled selected variant
        assert nav._dest_parts[1].icon.icon == ft.Icons.TABLE_CHART
        assert nav._dest_parts[0].icon.icon == ft.Icons.DASHBOARD_OUTLINED

    def test_setter_ignores_out_of_range(self):
        nav = _make()
        nav.selected_index = 99
        assert nav.selected_index == 0
        nav.selected_index = -1
        assert nav.selected_index == 0

    def test_setter_does_not_fire_on_select(self):
        """Only user clicks fire on_select. Programmatic writes are silent
        so the dashboard's dirty-CC-card guard never sees its own rollback
        as a fresh user action."""
        calls: list[int] = []
        nav = _make(on_select=calls.append)
        nav.selected_index = 2
        assert calls == []


class TestLastRefresh:
    """The timestamp under the Refresh action is driven by set_last_refresh."""

    def test_starts_empty(self):
        nav = _make()
        assert nav._last_refresh_text.value == ""

    def test_set_updates_text(self):
        nav = _make()
        nav.set_last_refresh("Updated 2:27 PM")
        assert nav._last_refresh_text.value == "Updated 2:27 PM"


class TestStructure:
    """Smoke tests that the rail renders the expected destinations and uses
    the design-system width / surface color."""

    def test_three_destinations_rendered(self):
        nav = _make()
        assert len(nav._dest_parts) == 3
        assert [p.dest.label for p in nav._dest_parts] == [
            "Overview",
            "Transactions",
            "Adjustments",
        ]

    def test_uses_paper_surface_and_fixed_width(self):
        nav = _make()
        assert nav.bgcolor == tokens.PAPER
        # 184px is the rail-width design choice; if it moves, this test
        # is the place to update so the constraint stays load-bearing.
        assert nav.width == 184

    def test_footer_email_appears_when_provided(self):
        with_email = _make(user_email="user@example.com")
        # Tooltip carries the full address even when truncated visually.
        text_nodes = [c for c in _walk(with_email) if isinstance(c, ft.Text)]
        emails = [t for t in text_nodes if t.value == "user@example.com"]
        assert len(emails) == 1
        assert emails[0].tooltip == "user@example.com"

    def test_no_footer_when_email_empty(self):
        nav = _make(user_email="")
        text_values = [t.value for t in _walk(nav) if isinstance(t, ft.Text) and t.value]
        assert all("@" not in (v or "") for v in text_values)


def _walk(control: ft.Control):
    """Yield every control reachable from ``control`` via the usual child
    attributes Flet exposes."""
    seen: set[int] = set()
    stack: list[ft.Control] = [control]
    child_attrs = ("content", "controls", "leading", "trailing", "title", "subtitle")
    while stack:
        c = stack.pop()
        if id(c) in seen or c is None:
            continue
        seen.add(id(c))
        yield c
        for attr in child_attrs:
            child = getattr(c, attr, None)
            if child is None:
                continue
            if isinstance(child, list):
                stack.extend(item for item in child if item is not None)
            else:
                stack.append(child)
