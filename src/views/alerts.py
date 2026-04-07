"""Safety threshold alerts for the forecast."""

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
    date: date | None = None


def generate_alerts(
    forecast: ForecastResult,
    safety_threshold: float,
) -> list[Alert]:
    """Analyze a forecast and generate alerts for shortfalls and low balances."""
    alerts: list[Alert] = []

    # Critical: balance goes negative
    negative_days = [d for d in forecast.days if d.ending_balance < 0]
    if negative_days:
        first = negative_days[0]
        alerts.append(
            Alert(
                severity="critical",
                title="Account Overdraft",
                message=(
                    f"Balance projected to go negative on {first.date.strftime('%b %d')} "
                    f"(${first.ending_balance:,.2f}). "
                    f"{len(negative_days)} day(s) in the red."
                ),
                date=first.date,
            )
        )

    # Warning: balance drops below safety threshold (but stays positive)
    if safety_threshold > 0:
        below_threshold = [d for d in forecast.days if 0 <= d.ending_balance < safety_threshold]
        if below_threshold:
            first = below_threshold[0]
            alerts.append(
                Alert(
                    severity="warning",
                    title="Low Balance Warning",
                    message=(
                        f"Balance projected to drop below ${safety_threshold:,.0f} "
                        f"on {first.date.strftime('%b %d')} "
                        f"(${first.ending_balance:,.2f}). "
                        f"{len(below_threshold)} day(s) below threshold."
                    ),
                    date=first.date,
                )
            )

    # Info: large single-day drops
    for day in forecast.days:
        if day.net_change < -2000:
            alerts.append(
                Alert(
                    severity="info",
                    title="Large Outflow",
                    message=(
                        f"${abs(day.net_change):,.2f} going out on "
                        f"{day.date.strftime('%b %d')}: "
                        + ", ".join(t.name for t in day.transactions if t.amount < 0)
                    ),
                    date=day.date,
                )
            )

    # Sort: critical first, then warning, then info; within severity by date
    severity_order = {"critical": 0, "warning": 1, "info": 2}
    alerts.sort(key=lambda a: (severity_order.get(a.severity, 9), a.date or date.max))

    return alerts


def build_alerts_banner(alerts: list[Alert]) -> ft.Column:
    """Build a Flet Column of alert banners."""
    if not alerts:
        return ft.Column()

    banners = []
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

        banners.append(
            ft.Container(
                content=ft.Row(
                    [
                        ft.Icon(icon, color=icon_color, size=22),
                        ft.Column(
                            [
                                ft.Text(alert.title, weight=ft.FontWeight.BOLD, size=13),
                                ft.Text(alert.message, size=12),
                            ],
                            spacing=2,
                            expand=True,
                        ),
                    ],
                    spacing=12,
                ),
                padding=12,
                bgcolor=bg_color,
                border=ft.border.all(1, border_color),
                border_radius=8,
            )
        )

    return ft.Column(controls=banners, spacing=8)
