"""Accessibility regression tests.

Every ``ft.IconButton`` rendered by one of our view builders should be
wrapped in an ``ft.Semantics`` node with a non-empty ``label`` (or carry a
``semantics_label`` attribute itself). Tooltips alone are NOT read by
screen readers on Flet desktop, so "just set a tooltip" is not enough.

This test walks the control tree produced by each view/builder and fails
with the path to any icon button that lacks an accessible name.
"""

from __future__ import annotations

from datetime import date

import flet as ft

from src.data.models import ForecastTransaction
from src.forecast.models import ForecastDay, ForecastResult


def _make_forecast(balance: float = 5000.0, days_out: int = 7) -> ForecastResult:
    days: list[ForecastDay] = []
    b = balance
    for i in range(days_out):
        d = date(2026, 1, 1 + i)
        txns: list[ForecastTransaction] = []
        if i == 2:
            txns = [ForecastTransaction(date=d, name="Rent", amount=-1500.0, category="Housing")]
        elif i == 4:
            txns = [
                ForecastTransaction(
                    date=d,
                    name="Chase Sapphire Payment (1/5)",
                    amount=-300.0,
                    category="Credit Card Payment",
                )
            ]
        elif i == 5:
            txns = [
                ForecastTransaction(
                    date=d,
                    name="Car repair",
                    amount=-400.0,
                    category="Adjustment",
                )
            ]
        day = ForecastDay(date=d, starting_balance=b, transactions=txns)
        b = day.ending_balance
        days.append(day)
    return ForecastResult(days=days, starting_balance=balance, safety_threshold=500.0)


def _iter_children(control: ft.Control):
    """Yield every child control reachable from ``control``.

    Flet controls expose their children under a handful of attribute names
    (``content``, ``controls``, ``actions``, ``title``, etc.) — walk them
    all so we can find deeply nested IconButtons.
    """
    seen: set[int] = set()
    stack: list[ft.Control] = [control]
    child_attrs = (
        "content",
        "controls",
        "actions",
        "title",
        "subtitle",
        "leading",
        "trailing",
        "destinations",
        "cells",
        "rows",
        "columns",
        "tabs",
    )
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
                for item in child:
                    if item is not None:
                        stack.append(item)
            else:
                stack.append(child)


def _assert_every_icon_button_is_labeled(root: ft.Control, context: str) -> None:
    """Fail if any IconButton under ``root`` lacks a Semantics(label=...) ancestor.

    We walk the tree; when we encounter a Semantics node whose content (or
    subtree) contains an IconButton, we mark that button as labeled as
    long as the Semantics has a non-empty ``label``. Any unlabeled
    IconButton raises.
    """
    labeled_buttons: set[int] = set()

    # Pass 1: mark buttons that live under a labeled Semantics ancestor.
    for node in _iter_children(root):
        if isinstance(node, ft.Semantics) and node.label:
            for descendant in _iter_children(node):
                if isinstance(descendant, ft.IconButton):
                    labeled_buttons.add(id(descendant))

    # Pass 2: any IconButton not marked is unlabeled.
    unlabeled: list[str] = []
    for node in _iter_children(root):
        if isinstance(node, ft.IconButton) and id(node) not in labeled_buttons:
            unlabeled.append(
                f"icon={getattr(node, 'icon', '?')} tooltip={getattr(node, 'tooltip', '?')!r}"
            )

    assert not unlabeled, (
        f"{context}: found IconButton(s) without an accessible name — wrap them in "
        f"ft.Semantics(button=True, label=...):\n  " + "\n  ".join(unlabeled)
    )


class TestIconButtonLabels:
    """Every icon-only button should have a screen-reader accessible name."""

    def test_alerts_banner_icon_buttons(self):
        from src.views.alerts import Alert, build_alerts_banner

        alerts = [
            Alert(severity="critical", title="Overdraft", message="Balance negative"),
            Alert(severity="warning", title="Low", message="Below threshold"),
            Alert(severity="info", title="Large outflow", message="$3000 going out"),
        ]
        banner = build_alerts_banner(alerts)
        _assert_every_icon_button_is_labeled(banner, "build_alerts_banner")

    def test_transactions_table_icon_buttons(self):
        from src.views.transactions_table import build_transactions_table

        forecast = _make_forecast()
        table = build_transactions_table(
            forecast,
            on_edit_cc=lambda _t: None,
            on_edit_oneoff=lambda _t: None,
            on_edit_recurring=lambda _t: None,
        )
        _assert_every_icon_button_is_labeled(table, "build_transactions_table")

    def test_update_banner_icon_buttons(self):
        from src.views.update_banner import build_update_banner

        banner = build_update_banner(
            {
                "version": "0.2.0",
                "download_url": "https://example.com/dl",
                "html_url": "https://example.com",
            }
        )
        _assert_every_icon_button_is_labeled(banner, "build_update_banner")

    def test_adjustments_panel_icon_buttons(self):
        from src.data.models import RecurringItem
        from src.views.adjustments import AdjustmentsPanel

        items = [
            RecurringItem(
                name="Netflix",
                amount=-15.99,
                frequency="monthly",
                base_date=date(2026, 1, 15),
                category="Entertainment",
            ),
        ]
        panel = AdjustmentsPanel(recurring_items=items, on_change=lambda: None)
        # Force the override row rebuild so the Reset IconButton exists.
        panel._rebuild_override_rows()
        _assert_every_icon_button_is_labeled(panel, "AdjustmentsPanel")

    def test_dashboard_icon_buttons(self, patched_session_manager):
        from src.views.dashboard import DashboardView

        dashboard = DashboardView(session_manager=patched_session_manager, on_logout=lambda: None)
        _assert_every_icon_button_is_labeled(dashboard, "DashboardView")

    def test_login_view_icon_buttons(self, patched_session_manager):
        from src.auth.login_view import LoginView

        view = LoginView(
            session_manager=patched_session_manager,
            on_login_success=lambda: None,
            on_demo=lambda: None,
        )
        _assert_every_icon_button_is_labeled(view, "LoginView")


class TestChartSummary:
    """The chart must ship a text summary for screen-reader users."""

    def test_summary_mentions_balance_range(self):
        from src.views.chart import build_forecast_chart_summary

        forecast = _make_forecast()
        summary = build_forecast_chart_summary(forecast)
        # Key facts a non-visual user needs
        assert "Balance projection" in summary
        assert "starts at" in summary
        assert "ends at" in summary
        # And we direct them to the accessible text alternative
        assert "Transactions tab" in summary

    def test_summary_handles_empty(self):
        from src.views.chart import build_forecast_chart_summary

        forecast = ForecastResult(days=[], starting_balance=0.0, safety_threshold=0.0)
        summary = build_forecast_chart_summary(forecast)
        assert summary  # not empty


class TestAlertsLiveRegion:
    """The alerts banner must be a live region for screen-reader announcement."""

    def test_alerts_banner_is_live_region(self):
        from src.views.alerts import Alert, build_alerts_banner

        alerts = [
            Alert(severity="critical", title="Overdraft", message="Balance negative"),
        ]
        banner = build_alerts_banner(alerts)
        assert isinstance(banner, ft.Semantics)
        assert banner.live_region is True
        assert banner.label, "alerts banner should advertise a non-empty summary"
