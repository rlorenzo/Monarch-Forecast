"""Unit tests for the editorial left-hand nav (SideNav).

Focused on the component's state machine and public API. Visual rendering
is exercised by ``tests/test_views_smoke.py`` (via DashboardView) and by
the accessibility regression suite in ``tests/test_accessibility.py``.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import flet as ft

from src.views import tokens
from src.views.side_nav import _STALE_GLYPH, NavDestination, SideNav, _format_last_refresh


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
    """The timestamp under the Refresh action is driven by set_last_refresh.

    The label is rendered relative to the stored ``datetime`` so the
    user can immediately tell whether the underlying forecast is
    minutes, hours, or days old.
    """

    def test_starts_empty(self):
        nav = _make()
        assert nav._last_refresh_text.value == ""
        assert nav._last_refresh_dt is None

    def test_set_renders_relative_label(self):
        nav = _make()
        nav.set_last_refresh(datetime.now())
        # A fresh-now stamp should land in the "Just now" bucket.
        assert nav._last_refresh_text.value == "Just now"

    def test_set_with_none_clears_label(self):
        nav = _make()
        nav.set_last_refresh(datetime.now())
        nav.set_last_refresh(None)
        assert nav._last_refresh_text.value == ""

    def test_stale_data_prepends_glyph(self):
        """Staleness must be conveyed by something other than colour.

        ``SIGNAL_THRESHOLD`` on ``PAPER`` lands at ~2.14:1 contrast,
        below the WCAG AA 4.5:1 bar for small text, so the rail uses a
        leading ⚠ glyph instead.
        """
        nav = _make()
        nav.set_last_refresh(datetime.now() - timedelta(hours=13))
        assert nav._last_refresh_text.value is not None
        assert nav._last_refresh_text.value.startswith(f"{_STALE_GLYPH} ")

    def test_fresh_data_has_no_glyph(self):
        nav = _make()
        nav.set_last_refresh(datetime.now() - timedelta(minutes=5))
        assert nav._last_refresh_text.value is not None
        assert _STALE_GLYPH not in nav._last_refresh_text.value

    def test_stale_data_announces_via_semantics(self):
        """Screen readers don't observe colour. The ``semantics_label``
        must explicitly mention that the data is stale."""
        nav = _make()
        nav.set_last_refresh(datetime.now() - timedelta(hours=13))
        assert nav._last_refresh_text.semantics_label is not None
        assert "(stale)" in nav._last_refresh_text.semantics_label
        assert nav._last_refresh_text.semantics_label.startswith("Last refreshed:")

    def test_fresh_data_announces_without_stale_suffix(self):
        nav = _make()
        nav.set_last_refresh(datetime.now() - timedelta(minutes=5))
        assert nav._last_refresh_text.semantics_label is not None
        assert "(stale)" not in nav._last_refresh_text.semantics_label

    def test_none_clears_semantics_and_tooltip(self):
        nav = _make()
        nav.set_last_refresh(datetime.now())
        nav.set_last_refresh(None)
        assert nav._last_refresh_text.semantics_label is None
        assert nav._last_refresh_text.tooltip is None

    def test_tooltip_mirrors_visible_label(self):
        """At 150%+ system text scale the label ellipsizes inside the
        184px rail. The tooltip preserves the full string so keyboard
        and mouse users can still recover it on hover/focus."""
        nav = _make()
        nav.set_last_refresh(datetime.now() - timedelta(hours=2))
        assert nav._last_refresh_text.tooltip == nav._last_refresh_text.value

    def test_label_is_capped_to_one_line(self):
        """Guards the 184px rail width against label wrapping.

        The longest possible label ("Yesterday, 12:00 PM") sits at the
        edge of the timestamp column. Without ``max_lines=1`` and an
        ellipsis overflow, a font bump or rail-width change would wrap
        the label onto a second line and push the Sign-out row down.
        """
        nav = _make()
        assert nav._last_refresh_text.max_lines == 1
        assert nav._last_refresh_text.overflow == ft.TextOverflow.ELLIPSIS


class TestFormatLastRefresh:
    """Each bucket of the relative-time formatter."""

    def test_none_is_empty(self):
        text, stale = _format_last_refresh(None, datetime(2026, 5, 25, 16, 0))
        assert text == ""
        assert stale is False

    def test_under_a_minute_is_just_now(self):
        now = datetime(2026, 5, 25, 16, 0)
        text, stale = _format_last_refresh(now - timedelta(seconds=30), now)
        assert text == "Just now"
        assert stale is False

    def test_future_clock_drift_is_just_now(self):
        # If the stored datetime drifts ahead of "now" by a few seconds
        # (clock skew on resume), the label shouldn't render a negative
        # minute count.
        now = datetime(2026, 5, 25, 16, 0)
        text, _ = _format_last_refresh(now + timedelta(seconds=3), now)
        assert text == "Just now"

    def test_minutes_within_the_hour(self):
        now = datetime(2026, 5, 25, 16, 0)
        text, _ = _format_last_refresh(now - timedelta(minutes=5), now)
        assert text == "5 min ago"

    def test_today_shows_clock_time(self):
        now = datetime(2026, 5, 25, 16, 0)
        text, _ = _format_last_refresh(now - timedelta(hours=2), now)
        assert text == "Today, 2:00 PM"

    def test_today_morning_renders_am(self):
        now = datetime(2026, 5, 25, 16, 0)
        text, _ = _format_last_refresh(datetime(2026, 5, 25, 8, 5), now)
        assert text == "Today, 8:05 AM"

    def test_today_noon_and_midnight(self):
        now = datetime(2026, 5, 25, 16, 0)
        text_noon, _ = _format_last_refresh(datetime(2026, 5, 25, 12, 0), now)
        assert text_noon == "Today, 12:00 PM"
        text_midnight, _ = _format_last_refresh(datetime(2026, 5, 25, 0, 0), now)
        assert text_midnight == "Today, 12:00 AM"

    def test_yesterday(self):
        now = datetime(2026, 5, 25, 16, 0)
        text, _ = _format_last_refresh(datetime(2026, 5, 24, 17, 0), now)
        assert text == "Yesterday, 5:00 PM"

    def test_days_ago(self):
        now = datetime(2026, 5, 25, 16, 0)
        text, _ = _format_last_refresh(datetime(2026, 5, 22, 9, 0), now)
        assert text == "3 days ago"

    def test_older_than_a_week_shows_date(self):
        now = datetime(2026, 5, 25, 16, 0)
        text, _ = _format_last_refresh(datetime(2026, 5, 1, 9, 0), now)
        assert text == "May 1, 2026"

    def test_stale_flag_kicks_in_after_12_hours(self):
        now = datetime(2026, 5, 25, 16, 0)
        _, stale_11h = _format_last_refresh(now - timedelta(hours=11), now)
        _, stale_13h = _format_last_refresh(now - timedelta(hours=13), now)
        assert stale_11h is False
        assert stale_13h is True

    def test_month_abbreviations_are_locale_invariant(self):
        """Regression guard: ``strftime('%b')`` honours the active locale
        and would print ``Mai`` / ``mai`` under German / French CI. The
        formatter uses a hardcoded English list instead."""
        now = datetime(2027, 1, 1, 12, 0)
        expected = [
            "Jan",
            "Feb",
            "Mar",
            "Apr",
            "May",
            "Jun",
            "Jul",
            "Aug",
            "Sep",
            "Oct",
            "Nov",
            "Dec",
        ]
        for month, name in enumerate(expected, start=1):
            text, _ = _format_last_refresh(datetime(2025, month, 15, 12, 0), now)
            assert text.startswith(f"{name} 15, 2025"), text


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
