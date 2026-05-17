"""Tests for the alerts banner dismiss flow.

``build_alerts_banner`` returns either an empty Container (no alerts)
or a Semantics live-region wrapping a Column of Container banners.
Each banner exposes a Dismiss IconButton that pops the alert and
updates the live-region label.

The Container .update() inside the dismiss handler raises on an
unmounted view; the handler catches RuntimeError, so tests can call
the dismiss closure directly.
"""

from __future__ import annotations

from datetime import date
from typing import Any
from unittest.mock import MagicMock

import flet as ft

from src.data.models import ForecastTransaction
from src.forecast.models import ForecastDay, ForecastResult
from src.views.alerts import (
    Alert,
    build_alerts_banner,
    build_alerts_summary,
    generate_alerts,
)


def _m(obj: Any) -> Any:
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


def _find_dismiss_buttons(banner: Any) -> list[ft.IconButton]:
    return [c for c in _walk(banner) if isinstance(c, ft.IconButton) and c.icon == ft.Icons.CLOSE]


# ---------------------------------------------------------------------------
# build_alerts_banner
# ---------------------------------------------------------------------------


class TestEmptyAlerts:
    def test_no_alerts_returns_empty_container(self):
        result = build_alerts_banner([])
        assert isinstance(result, ft.Container)
        # No content — Flet rejects zero-size Semantics, so banner is bare.
        assert result.content is None


class TestSeverityStyling:
    def test_critical_uses_negative_signal_color(self):
        from src.views import tokens

        alert = Alert(severity="critical", title="Overdraft", message="msg")
        wrapper = build_alerts_banner([alert])
        # The critical icon uses ERROR which maps to signal-negative.
        for c in _walk(wrapper):
            if isinstance(c, ft.Icon) and c.icon == ft.Icons.ERROR:
                assert c.color == tokens.SIGNAL_NEGATIVE
                break
        else:
            raise AssertionError("Critical icon not found")

    def test_warning_uses_threshold_color(self):
        from src.views import tokens

        alert = Alert(severity="warning", title="Low", message="msg")
        wrapper = build_alerts_banner([alert])
        found = False
        for c in _walk(wrapper):
            if isinstance(c, ft.Icon) and c.icon == ft.Icons.WARNING_AMBER:
                assert c.color == tokens.SIGNAL_THRESHOLD
                found = True
                break
        assert found

    def test_info_uses_ink_color(self):
        from src.views import tokens

        alert = Alert(severity="info", title="FYI", message="msg")
        wrapper = build_alerts_banner([alert])
        for c in _walk(wrapper):
            if isinstance(c, ft.Icon) and c.icon == ft.Icons.INFO_OUTLINE:
                assert c.color == tokens.INK_2
                break
        else:
            raise AssertionError("Info icon not found")


# ---------------------------------------------------------------------------
# Dismiss flow
# ---------------------------------------------------------------------------


class TestDismissFlow:
    def test_single_dismiss_swaps_to_empty_container(self):
        alert = Alert(severity="critical", title="Overdraft", message="msg")
        wrapper = build_alerts_banner([alert])
        assert isinstance(wrapper, ft.Semantics)
        # Stub update so the unmounted Semantics doesn't raise.
        _m(wrapper).update = MagicMock()
        dismiss_btns = _find_dismiss_buttons(wrapper)
        assert len(dismiss_btns) == 1
        _m(dismiss_btns[0].on_click)(MagicMock())
        # All alerts dismissed → content swapped to empty Container.
        assert isinstance(wrapper.content, ft.Container)
        assert wrapper.label == ""

    def test_dismiss_one_of_two_preserves_other(self):
        alerts = [
            Alert(severity="critical", title="First", message="m1"),
            Alert(severity="warning", title="Second", message="m2"),
        ]
        wrapper = build_alerts_banner(alerts)
        assert isinstance(wrapper, ft.Semantics)
        _m(wrapper).update = MagicMock()
        dismiss_btns = _find_dismiss_buttons(wrapper)
        assert len(dismiss_btns) == 2
        # Dismiss the first one.
        _m(dismiss_btns[0].on_click)(MagicMock())
        # Inner Column should still have one banner.
        inner = wrapper.content
        assert isinstance(inner, ft.Column)
        assert len(inner.controls) == 1
        # Live-region label updated to the survivor.
        assert "Second" in (wrapper.label or "")


# ---------------------------------------------------------------------------
# build_alerts_summary (used by the live region label)
# ---------------------------------------------------------------------------


class TestAlertsSummary:
    def test_empty_alerts_returns_empty_string(self):
        assert build_alerts_summary([]) == ""

    def test_single_alert_uses_singular_phrasing(self):
        alerts = [Alert(severity="critical", title="X", message="boom")]
        summary = build_alerts_summary(alerts)
        assert summary.startswith("1 alert:")
        assert "Critical: X. boom" in summary

    def test_multi_alert_uses_plural(self):
        alerts = [
            Alert(severity="critical", title="A", message="m1"),
            Alert(severity="warning", title="B", message="m2"),
        ]
        summary = build_alerts_summary(alerts)
        assert summary.startswith("2 alerts:")
        assert "Critical: A" in summary
        assert "Warning: B" in summary


# ---------------------------------------------------------------------------
# generate_alerts: branches that the existing suite doesn't cover
# ---------------------------------------------------------------------------


def _forecast_with_days(
    days_payload: list[tuple[date, float, list[ForecastTransaction]]],
) -> ForecastResult:
    days = [
        ForecastDay(date=d, starting_balance=bal, transactions=txns)
        for d, bal, txns in days_payload
    ]
    return ForecastResult(days=days, starting_balance=days_payload[0][1], safety_threshold=500.0)


class TestGenerateAlertsBranches:
    def test_critical_overdraft_alone(self):
        # Negative balance with no threshold band → "Account Overdraft" alert
        # (not the combined "Overdraft & Below Threshold" variant).
        days = [
            (
                date(2026, 6, 1),
                100.0,
                [ForecastTransaction(date=date(2026, 6, 1), name="X", amount=-200.0)],
            )
        ]
        result = _forecast_with_days(days)
        alerts = generate_alerts(result, safety_threshold=0)
        assert any(a.title == "Account Overdraft" for a in alerts)

    def test_low_balance_warning_when_in_band_only(self):
        # Balance dips into threshold band but never negative → warning.
        days = [
            (
                date(2026, 6, 1),
                1000.0,
                [ForecastTransaction(date=date(2026, 6, 1), name="X", amount=-600.0)],
            ),
        ]
        result = _forecast_with_days(days)
        alerts = generate_alerts(result, safety_threshold=500)
        assert any(a.title == "Low Balance Warning" for a in alerts)

    def test_combined_alert_when_drops_to_negative_without_band(self):
        # Balance plummets from above-threshold straight to negative on a
        # single day → combined critical alert.
        days = [
            (
                date(2026, 6, 1),
                5000.0,
                [ForecastTransaction(date=date(2026, 6, 1), name="Big", amount=-5500.0)],
            ),
        ]
        result = _forecast_with_days(days)
        alerts = generate_alerts(result, safety_threshold=500)
        assert any(a.title == "Overdraft & Below Safety Threshold" for a in alerts)

    def test_large_outflow_single_day(self):
        # Net day change < -$2000 → "Large Outflow" info alert.
        days = [
            (
                date(2026, 6, 1),
                10_000.0,
                [
                    ForecastTransaction(date=date(2026, 6, 1), name="Rent", amount=-3000.0),
                ],
            ),
        ]
        result = _forecast_with_days(days)
        alerts = generate_alerts(result, safety_threshold=0)
        outflow = next(a for a in alerts if a.title.startswith("Large Outflow"))
        assert "Rent" in outflow.message

    def test_multiple_large_outflows_bullet_list(self):
        days = [
            (
                date(2026, 6, 1),
                20_000.0,
                [ForecastTransaction(date=date(2026, 6, 1), name="A", amount=-3000.0)],
            ),
            (
                date(2026, 6, 2),
                17_000.0,
                [ForecastTransaction(date=date(2026, 6, 2), name="B", amount=-3500.0)],
            ),
        ]
        result = _forecast_with_days(days)
        alerts = generate_alerts(result, safety_threshold=0)
        outflow = next(a for a in alerts if a.title == "Large Outflows")
        # Plural title + newline-separated bullets in message.
        assert "\n" in outflow.message
        assert "A" in outflow.message and "B" in outflow.message
