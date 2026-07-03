"""Catch-all tests for remaining low-value coverage gaps.

These tests target individual branches the main coverage push didn't
hit — chart tooltip variants, calendar-popover null cells, credit-card
estimator edge cases, recurring-detector frequency edges, side-nav
hover/logo handlers. Each test is small and direct; the file is here
to keep these one-offs from sprawling across category-named files.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import flet as ft

from src.data.models import ForecastTransaction, RecurringItem
from src.forecast.credit_cards import (
    _day_minus,
    _is_cc_payment_txn,
    _next_month_day,
    _prev_month_day,
    estimate_cc_payments,
    infer_due_day,
)
from src.forecast.models import ForecastDay, ForecastResult
from src.views.chart import _build_tooltip, build_forecast_chart
from src.views.side_nav import NavDestination, SideNav


def _m(obj: Any) -> Any:
    return obj


# ---------------------------------------------------------------------------
# Chart
# ---------------------------------------------------------------------------


class TestChartEmptyResult:
    def test_no_days_returns_bare_chart(self):
        result = ForecastResult(days=[], starting_balance=0.0, safety_threshold=0.0)
        chart = build_forecast_chart(result)
        # Bare chart with the fixed height — no data series.
        assert chart.height is not None


class TestTooltipBuilder:
    def test_single_day_tooltip_no_net_line(self):
        day = ForecastDay(
            date=date(2026, 6, 1),
            starting_balance=1000.0,
            transactions=[
                ForecastTransaction(date=date(2026, 6, 1), name="Rent", amount=-1500.0),
            ],
        )
        text = _build_tooltip(day)
        # Single transaction → no "Net" line.
        assert "Net" not in text
        assert "Rent" in text

    def test_multi_day_tooltip_with_negative_net(self):
        day = ForecastDay(
            date=date(2026, 6, 1),
            starting_balance=5000.0,
            transactions=[
                ForecastTransaction(date=date(2026, 6, 1), name="Rent", amount=-1500.0),
                ForecastTransaction(date=date(2026, 6, 1), name="Util", amount=-100.0),
            ],
        )
        text = _build_tooltip(day)
        assert "Net: -$1,600" in text

    def test_multi_day_tooltip_with_positive_net(self):
        day = ForecastDay(
            date=date(2026, 6, 1),
            starting_balance=1000.0,
            transactions=[
                ForecastTransaction(date=date(2026, 6, 1), name="Salary", amount=3000.0),
                ForecastTransaction(date=date(2026, 6, 1), name="Bonus", amount=500.0),
            ],
        )
        text = _build_tooltip(day)
        assert "Net: +$3,500" in text

    def test_tooltip_caps_transaction_list_at_four(self):
        day = ForecastDay(
            date=date(2026, 6, 1),
            starting_balance=10_000.0,
            transactions=[
                ForecastTransaction(date=date(2026, 6, 1), name=f"Txn{i}", amount=-10.0)
                for i in range(7)
            ],
        )
        text = _build_tooltip(day)
        assert "+3 more" in text


def _make_windowed_forecast(days_out: int) -> ForecastResult:
    """A bare balance-only forecast spanning ``days_out`` days.

    Uses ``timedelta`` (unlike ``tests.factories.make_forecast``, which
    overflows past January because it adds directly to the day-of-month)
    so this works for windows longer than a month, e.g. the default 45-day
    view.
    """
    start = date(2026, 1, 1)
    days = [
        ForecastDay(date=start + timedelta(days=i), starting_balance=1000.0, transactions=[])
        for i in range(days_out)
    ]
    return ForecastResult(days=days, starting_balance=1000.0, safety_threshold=500.0)


class TestChartAxisLabels:
    """Regression: the final day must always get an x-axis label.

    ``label_interval = total_days // 6`` rarely divides total_days evenly
    (44 // 6 == 7 for a 45-day window, and 44 % 7 != 0), so the old
    modulo-only placement left the forecast's last day unlabeled at every
    common window size.
    """

    def test_last_day_always_labeled_at_default_window(self):
        forecast = _make_windowed_forecast(45)
        chart = build_forecast_chart(forecast)
        assert chart.bottom_axis is not None
        total_days = (forecast.days[-1].date - forecast.days[0].date).days
        values = [lbl.value for lbl in chart.bottom_axis.labels]
        assert values.count(total_days) == 1
        last_label = chart.bottom_axis.labels[values.index(total_days)]
        label_text = last_label.label
        assert isinstance(label_text, ft.Text)
        assert label_text.value == forecast.days[-1].date.strftime("%b %d")

    def test_no_crowded_label_immediately_before_the_end(self):
        forecast = _make_windowed_forecast(45)
        chart = build_forecast_chart(forecast)
        assert chart.bottom_axis is not None
        values = sorted(lbl.value for lbl in chart.bottom_axis.labels)
        total_days = values[-1]
        label_interval = max(total_days // 6, 1)
        second_last = values[-2]
        # A regular-interval label within half an interval of the end
        # would crowd the always-shown final label, so it's dropped.
        assert total_days - second_last >= label_interval / 2


# ---------------------------------------------------------------------------
# Credit-card estimator branches
# ---------------------------------------------------------------------------


class TestCcEstimatorEdges:
    def test_positive_balance_skipped(self):
        cc_accounts = [{"id": "cc1", "name": "Card", "balance": 100.0}]
        result = estimate_cc_payments(cc_accounts, recurring_items=[], forecast_days=45)
        assert result == []

    def test_user_settings_but_no_charges_no_override_skipped(self):
        cc_accounts = [{"id": "cc1", "name": "Card", "balance": -200.0}]
        # Cycle settings provided, but no transactions → no cycle estimate.
        # Without an amount override, the card is skipped entirely.
        result = estimate_cc_payments(
            cc_accounts,
            recurring_items=[],
            forecast_days=45,
            transactions=[],
            cc_settings={"cc1": {"due_day": 15, "close_day": 20}},
        )
        assert result == []

    def test_user_settings_with_override_emits_payment(self):
        cc_accounts = [{"id": "cc1", "name": "Card", "balance": -200.0}]
        result = estimate_cc_payments(
            cc_accounts,
            recurring_items=[],
            forecast_days=45,
            transactions=[],
            cc_settings={"cc1": {"due_day": 15, "close_day": 20}},
            amount_overrides={"cc1": 250.0},
        )
        assert len(result) == 1
        # The override label is "manual".
        assert "manual" in result[0].name
        assert result[0].amount == -250.0

    def test_invalid_due_day_in_settings_skips_with_override(self):
        cc_accounts = [{"id": "cc1", "name": "Card", "balance": -200.0}]
        # Even with an override, if the settings' due_day is invalid we skip.
        result = estimate_cc_payments(
            cc_accounts,
            recurring_items=[],
            forecast_days=45,
            transactions=[],
            cc_settings={"cc1": {"due_day": 0, "close_day": 20}},
            amount_overrides={"cc1": 250.0},
        )
        assert result == []

    def test_balance_fallback_skipped_when_due_outside_window(self):
        # Forecast window of only 5 days but the fallback due date is
        # today + 25 days — should skip.
        cc_accounts = [{"id": "cc1", "name": "Card", "balance": -200.0}]
        result = estimate_cc_payments(
            cc_accounts,
            recurring_items=[],
            forecast_days=5,
            transactions=[],
        )
        assert result == []


class TestInferDueDay:
    def test_no_payments_returns_zero(self):
        assert infer_due_day("Chase", []) == 0

    def test_skips_outflow_with_amount_zero(self):
        # The classifier treats amount >= 0 as "not a payment" — skipped.
        txns = [
            {
                "amount": 0.0,
                "date": "2026-06-15",
                "merchant": {"name": "Chase Card Payment"},
                "category": {"name": "Transfer"},
                "account": {"id": "checking"},
            },
        ]
        assert infer_due_day("Chase Sapphire", txns) == 0

    def test_skips_invalid_date_in_payment(self):
        txns = [
            {
                "amount": -100.0,
                "date": "garbage",
                "merchant": {"name": "Chase Card Payment"},
                "category": {"name": "Transfer"},
                "account": {"id": "checking"},
            },
        ]
        assert infer_due_day("Chase Sapphire", txns) == 0

    def test_uses_most_common_day(self):
        txns = []
        # Payment day = 15 (3x) vs day = 16 (1x) → 15 wins.
        for d in ("2026-04-15", "2026-05-15", "2026-06-15", "2026-07-16"):
            txns.append(
                {
                    "amount": -100.0,
                    "date": d,
                    "merchant": {"name": "Chase Sapphire Payment"},
                    "category": {"name": "Credit Card Payment"},
                    "account": {"id": "checking"},
                }
            )
        assert infer_due_day("Chase Sapphire", txns) == 15


class TestIsCcPaymentTxn:
    def test_short_name_falls_back_to_payment_word(self):
        # Single-letter CC name → no usable keywords → relies on
        # payment-word match alone.
        assert _is_cc_payment_txn("monthly payment", "a") is True
        assert _is_cc_payment_txn("monthly grocery", "a") is False


class TestPrevNextMonthDay:
    def test_prev_month_wraps_to_december_of_prior_year(self):
        ref = date(2026, 1, 15)
        result = _prev_month_day(ref, day=20)
        assert result == date(2025, 12, 20)

    def test_next_month_wraps_to_january_of_next_year(self):
        ref = date(2026, 12, 15)
        result = _next_month_day(ref, day=5)
        assert result == date(2027, 1, 5)

    def test_next_month_day_with_same_month_if_later(self):
        ref = date(2026, 6, 5)
        result = _next_month_day(ref, day=20)
        assert result == date(2026, 6, 20)


class TestDayMinus:
    def test_caps_at_28(self):
        # Subtracting nothing from a day past 28 — caps to 28.
        assert _day_minus(31, 0) == 28

    def test_negative_wraps_to_within_month(self):
        # day=5, subtract 10 → -5 → +30 = 25 → cap 25.
        assert _day_minus(5, 10) == 25


# ---------------------------------------------------------------------------
# RecurringItem fallback path
# ---------------------------------------------------------------------------


class TestEstimateUsesRecurringFallback:
    def test_recurring_fallback_when_no_settings_no_history(self):
        cc_accounts = [{"id": "cc1", "name": "Apple Card", "balance": -100.0}]
        recurring = [
            RecurringItem(
                name="Apple Card Payment",
                amount=-100.0,
                frequency="monthly",
                base_date=date.today() + timedelta(days=10),
                category="Credit Card Payment",
            ),
        ]
        result = estimate_cc_payments(
            cc_accounts,
            recurring_items=recurring,
            forecast_days=45,
            transactions=[],
        )
        # The fallback uses the recurring item's amount with label "avg".
        assert len(result) == 1
        assert "avg" in result[0].name


# ---------------------------------------------------------------------------
# Side nav hover + logo
# ---------------------------------------------------------------------------


def _make_side_nav(icon_path: str | None = None) -> SideNav:
    return SideNav(
        destinations=[
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
        ],
        on_select=lambda _i: None,
        on_refresh=lambda: None,
        on_logout=lambda: None,
        user_email="user@example.com",
        icon_path=icon_path,
    )


class TestSideNavLogo:
    def test_logo_hover_in_scales_and_rings(self):
        nav = _make_side_nav(icon_path="data:image/png;base64,XX")
        assert nav._logo_seal is not None
        seal = nav._logo_seal
        _m(seal).update = MagicMock()
        # Hover in.
        _m(nav._on_logo_hover)(SimpleNamespace(data="true", control=seal))
        scale = seal.scale
        assert scale is not None and getattr(scale, "scale", 1.0) > 1.0

    def test_logo_hover_out_restores_scale(self):
        nav = _make_side_nav(icon_path="data:image/png;base64,XX")
        seal = nav._logo_seal
        assert seal is not None
        _m(seal).update = MagicMock()
        _m(nav._on_logo_hover)(SimpleNamespace(data="false", control=seal))
        scale = seal.scale
        assert scale is not None and getattr(scale, "scale", 1.0) == 1.0

    def test_logo_hover_unmounted_does_not_raise(self):
        """``seal`` is a real, never-mounted Container here (``update`` is
        NOT stubbed) — ``update()`` raises ``RuntimeError`` on an unmounted
        control, and the handler must swallow that the same way its sibling
        methods (``refresh_display``, ``_repaint_destinations``) do."""
        nav = _make_side_nav(icon_path="data:image/png;base64,XX")
        seal = nav._logo_seal
        assert seal is not None
        nav._on_logo_hover(_m(SimpleNamespace(data="true", control=seal)))
        assert seal.scale is not None and getattr(seal.scale, "scale", 1.0) > 1.0

    def test_logo_click_routes_to_first_destination(self):
        picked: list[int] = []
        nav = SideNav(
            destinations=[
                NavDestination(
                    icon=ft.Icons.DASHBOARD_OUTLINED,
                    selected_icon=ft.Icons.DASHBOARD,
                    label="Overview",
                ),
            ],
            on_select=lambda i: picked.append(i),
            on_refresh=lambda: None,
            on_logout=lambda: None,
            user_email="",
            icon_path="data:image/png;base64,XX",
        )
        _m(nav._on_logo_click)(SimpleNamespace())
        assert picked == [0]

    def test_logo_click_with_no_destinations_is_noop(self):
        picked: list[int] = []
        # Use a NoOp nav whose destinations list is empty.
        nav = SideNav(
            destinations=[],
            on_select=lambda i: picked.append(i),
            on_refresh=lambda: None,
            on_logout=lambda: None,
            user_email="",
            icon_path=None,
        )
        # Build the click handler indirectly by directly invoking the
        # internal method when present. No destinations → handler exits.
        _m(nav._on_logo_click)(SimpleNamespace())
        assert picked == []


class TestSideNavSelectionRepaint:
    def test_set_last_refresh_updates_text(self):
        nav = _make_side_nav()
        nav.set_last_refresh(datetime.now())
        assert nav._last_refresh_text.value == "Just now"

    def test_selected_index_setter_out_of_range_noop(self):
        nav = _make_side_nav()
        prior = nav.selected_index
        nav.selected_index = 99
        assert nav.selected_index == prior

    def test_selected_index_setter_same_value_noop(self):
        nav = _make_side_nav()
        # Setting same index should not raise/repaint.
        nav.selected_index = nav.selected_index
