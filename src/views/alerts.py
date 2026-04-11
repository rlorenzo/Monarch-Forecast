"""Safety threshold alerts for the forecast."""

from __future__ import annotations

import datetime as _dt
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

import flet as ft

from src.forecast.models import ForecastResult


@dataclass
class Alert:
    """A single forecast alert."""

    severity: str  # "critical", "warning", "info"
    title: str
    message: str
    # Use `_dt.date` rather than `date` so the field name doesn't shadow
    # the type when the dataclass annotations are evaluated. The project
    # pattern is documented in CLAUDE.md — `from __future__ import
    # annotations` is not enough on its own because the dataclass decorator
    # evaluates the stringified annotation in the class scope, where
    # `date` refers to the field's default (None).
    date: _dt.date | None = None


def generate_alerts(
    forecast: ForecastResult,
    safety_threshold: float,
) -> list[Alert]:
    """Analyze a forecast and generate alerts for shortfalls and low balances."""
    alerts: list[Alert] = []

    negative_days = [d for d in forecast.days if d.ending_balance < 0]
    first_negative = negative_days[0] if negative_days else None

    # Non-negative "threshold band" days: below the cushion but still positive.
    band_days: list = []
    if safety_threshold > 0:
        band_days = [d for d in forecast.days if 0 <= d.ending_balance < safety_threshold]
    first_band = band_days[0] if band_days else None

    # Combined case: the account goes from above-threshold straight to negative
    # on a single day (skipping the positive-but-low band). That day is both a
    # threshold breach and an overdraft, so merge them into one critical alert.
    if safety_threshold > 0 and first_negative and not first_band:
        alerts.append(
            Alert(
                severity="critical",
                title="Overdraft & Below Safety Threshold",
                message=(
                    f"Balance projected to drop below ${safety_threshold:,.0f} and go "
                    f"negative on {first_negative.date.strftime('%b %d')} "
                    f"(${first_negative.ending_balance:,.2f}). "
                    f"{len(negative_days)} day(s) in the red."
                ),
                date=first_negative.date,
            )
        )
    else:
        if first_negative:
            alerts.append(
                Alert(
                    severity="critical",
                    title="Account Overdraft",
                    message=(
                        f"Balance projected to go negative on "
                        f"{first_negative.date.strftime('%b %d')} "
                        f"(${first_negative.ending_balance:,.2f}). "
                        f"{len(negative_days)} day(s) in the red."
                    ),
                    date=first_negative.date,
                )
            )
        if first_band:
            alerts.append(
                Alert(
                    severity="warning",
                    title="Low Balance Warning",
                    message=(
                        f"Balance projected to drop below ${safety_threshold:,.0f} "
                        f"on {first_band.date.strftime('%b %d')} "
                        f"(${first_band.ending_balance:,.2f}). "
                        f"{len(band_days)} day(s) below threshold."
                    ),
                    date=first_band.date,
                )
            )

    # Info: large single-day drops — collected into a single bulleted alert.
    large_outflow_days = [day for day in forecast.days if day.net_change < -2000]
    if large_outflow_days:
        if len(large_outflow_days) == 1:
            day = large_outflow_days[0]
            names = ", ".join(t.name for t in day.transactions if t.amount < 0)
            message = (
                f"${abs(day.net_change):,.2f} going out on {day.date.strftime('%b %d')}: {names}"
            )
        else:
            bullet_lines = []
            for day in large_outflow_days:
                names = ", ".join(t.name for t in day.transactions if t.amount < 0)
                bullet_lines.append(
                    f"\u2022 {day.date.strftime('%b %d')}: ${abs(day.net_change):,.2f} ({names})"
                )
            message = "\n".join(bullet_lines)
        alerts.append(
            Alert(
                severity="info",
                title=f"Large Outflow{'s' if len(large_outflow_days) > 1 else ''}",
                message=message,
                date=large_outflow_days[0].date,
            )
        )

    # Sort: critical first, then warning, then info; within severity by date
    severity_order = {"critical": 0, "warning": 1, "info": 2}
    alerts.sort(key=lambda a: (severity_order.get(a.severity, 9), a.date or date.max))

    return alerts


def _severity_word(severity: str) -> str:
    return {"critical": "Critical", "warning": "Warning", "info": "Info"}.get(
        severity, severity.title()
    )


def build_alerts_summary(alerts: list[Alert]) -> str:
    """Build a short spoken summary of the current alert set for screen readers."""
    if not alerts:
        return ""
    parts = [f"{len(alerts)} alert{'s' if len(alerts) != 1 else ''}:"]
    for alert in alerts:
        parts.append(f"{_severity_word(alert.severity)} — {alert.title}. {alert.message}")
    return " ".join(parts)


def build_alerts_banner(alerts: list[Alert]) -> ft.Control:
    """Build the alerts banner — a Semantics live region wrapping a Column
    of alert rows when there are alerts, or a plain empty Container when
    there are none.

    Dismissing a banner removes it from the column's control list so the
    column shrinks cleanly instead of leaving a gap where the hidden banner
    used to be. The outer Semantics node is a live region so assistive
    technologies announce new or changed alerts.

    When there are no alerts we intentionally skip the Semantics wrapper
    entirely — Flet rejects a Semantics whose content collapses to zero
    size, and an empty Column has no visible content.
    """
    if not alerts:
        return ft.Container()

    result_column = ft.Column(controls=[], spacing=8)
    wrapper = ft.Semantics(
        content=result_column,
        container=True,
        live_region=True,
        label=build_alerts_summary(alerts),
    )

    def make_dismiss(banner_control: ft.Container) -> Callable[[ft.Event[ft.IconButton]], None]:
        def handle(_: ft.Event[ft.IconButton]) -> None:
            try:
                result_column.controls.remove(banner_control)
            except ValueError:
                return
            try:
                result_column.update()
            except RuntimeError:
                pass

        return handle

    for alert in alerts:
        if alert.severity == "critical":
            icon = ft.Icons.ERROR
            bg_color = ft.Colors.RED_50
            icon_color = ft.Colors.RED
            border_color = ft.Colors.RED_200
        elif alert.severity == "warning":
            icon = ft.Icons.WARNING
            bg_color = ft.Colors.ORANGE_50
            icon_color = ft.Colors.ORANGE
            border_color = ft.Colors.ORANGE_200
        else:
            icon = ft.Icons.INFO_OUTLINE
            bg_color = ft.Colors.BLUE_50
            icon_color = ft.Colors.BLUE
            border_color = ft.Colors.BLUE_200

        severity_word = _severity_word(alert.severity)
        # Hold a direct reference to the IconButton so we can attach the
        # click handler after the banner Container is constructed (the
        # handler closes over the banner). Going through
        # ``Semantics.content`` would force us through ``Control | None``.
        dismiss_icon_button = ft.IconButton(
            icon=ft.Icons.CLOSE,
            icon_size=16,
            icon_color=icon_color,
            tooltip="Dismiss",
        )
        dismiss_button = ft.Semantics(
            button=True,
            label=f"Dismiss {severity_word.lower()} alert: {alert.title}",
            content=dismiss_icon_button,
        )

        banner = ft.Container(
            content=ft.Row(
                [
                    ft.Icon(
                        icon,
                        color=icon_color,
                        size=22,
                        semantics_label=f"{severity_word} alert",
                    ),
                    ft.Column(
                        [
                            ft.Text(alert.title, weight=ft.FontWeight.BOLD, size=13),
                            ft.Text(alert.message, size=12),
                        ],
                        spacing=2,
                        expand=True,
                    ),
                    dismiss_button,
                ],
                spacing=12,
            ),
            padding=12,
            bgcolor=bg_color,
            border=ft.Border.all(1, border_color),
            border_radius=8,
        )

        # The IconButton is nested inside the Semantics wrapper — attach the
        # dismiss handler to the underlying IconButton so the click lands on
        # the actual button control.
        dismiss_icon_button.on_click = make_dismiss(banner)
        result_column.controls.append(banner)

    return wrapper
