"""Balance timeline chart using flet-charts LineChart for native interactivity."""

import flet as ft
from flet_charts import (
    ChartAxis,
    ChartAxisLabel,
    ChartCirclePoint,
    ChartGridLines,
    LineChart,
    LineChartData,
    LineChartDataPoint,
    LineChartDataPointTooltip,
)

from src.forecast.models import ForecastResult

# Accessible green/red that work on both light and dark backgrounds
_GREEN = "#2E7D32"
_RED = "#C62828"
_GREEN_LIGHT = "#A5D6A7"
_RED_LIGHT = "#EF9A9A"


def build_forecast_chart(
    result: ForecastResult,
    height: float = 400,
) -> LineChart:
    """Create an interactive line chart with green/red coloring above/below $0."""
    if not result.days:
        return LineChart(height=height)

    start_date = result.days[0].date

    # Build all data points with tooltips
    all_points: list[dict] = []
    for day in result.days:
        x = (day.date - start_date).days
        tooltip_text = _build_tooltip(day)

        all_points.append(
            {
                "x": x,
                "y": day.ending_balance,
                "tooltip": tooltip_text,
            }
        )

    # Split into green (>= 0) and red (< 0) series
    green_series, red_series = _split_by_zero(all_points)

    data_series = []
    if green_series:
        data_series.append(
            LineChartData(
                points=green_series,
                color=_GREEN,
                stroke_width=2.5,
                curved=True,
                prevent_curve_over_shooting=True,
                below_line_bgcolor=ft.Colors.with_opacity(0.05, _GREEN),
            )
        )
    if red_series:
        data_series.append(
            LineChartData(
                points=red_series,
                color=_RED,
                stroke_width=2.5,
                curved=True,
                prevent_curve_over_shooting=True,
                below_line_bgcolor=ft.Colors.with_opacity(0.08, _RED),
            )
        )

    # X-axis labels
    total_days = all_points[-1]["x"] if all_points else 1
    label_interval = max(total_days // 6, 1)
    x_labels = []
    for day in result.days:
        day_offset = (day.date - start_date).days
        if day_offset % label_interval == 0:
            x_labels.append(
                ChartAxisLabel(
                    value=day_offset,
                    label=ft.Text(day.date.strftime("%b %d"), size=10),
                )
            )

    all_balances = [d.ending_balance for d in result.days]
    chart = LineChart(
        data_series=data_series,
        interactive=True,
        left_axis=ChartAxis(
            title=ft.Text("Balance ($)", size=12),
            label_size=60,
        ),
        bottom_axis=ChartAxis(
            labels=x_labels,
            label_size=30,
        ),
        horizontal_grid_lines=ChartGridLines(
            interval=max(abs(max(all_balances)) / 5, 1),
            color=ft.Colors.with_opacity(0.15, ft.Colors.ON_SURFACE),
        ),
        min_y=min(0, min(all_balances) * 1.1),
        max_y=max(all_balances) * 1.1,
        height=height,
        expand=True,
    )

    return chart


def _build_tooltip(day) -> str:
    """Build concise tooltip text for a data point."""
    lines = [f"{day.date.strftime('%b %d')}: ${day.ending_balance:,.2f}"]
    for txn in day.transactions[:4]:
        name = txn.name[:18]
        if txn.amount >= 0:
            lines.append(f"+${txn.amount:,.0f} {name}")
        else:
            lines.append(f"-${abs(txn.amount):,.0f} {name}")
    if len(day.transactions) > 4:
        lines.append(f"...+{len(day.transactions) - 4} more")
    if len(day.transactions) > 1:
        if day.net_change >= 0:
            lines.append(f"Net: +${day.net_change:,.0f}")
        else:
            lines.append(f"Net: -${abs(day.net_change):,.0f}")
    return "\n".join(lines)


def _make_point(
    x: float, y: float, tooltip: str = "", is_crossing: bool = False
) -> LineChartDataPoint:
    """Create a styled data point."""
    color = _GREEN if y >= 0 else _RED
    return LineChartDataPoint(
        x=x,
        y=y,
        tooltip=LineChartDataPointTooltip(
            text=tooltip,
            text_style=ft.TextStyle(
                color=ft.Colors.WHITE,
                size=11,
                weight=ft.FontWeight.W_500,
            ),
        )
        if tooltip
        else None,
        show_tooltip=bool(tooltip),
        point=ChartCirclePoint(radius=0 if is_crossing else 3, color=color),
        selected_point=ChartCirclePoint(radius=5, color=color),
    )


def _split_by_zero(
    points: list[dict],
) -> tuple[list[LineChartDataPoint], list[LineChartDataPoint]]:
    """Split data points into green (>=0) and red (<0) series.

    When the line crosses zero between two points, insert a crossing
    point at y=0 in both series for a clean color transition.
    """
    green: list[LineChartDataPoint] = []
    red: list[LineChartDataPoint] = []

    for i, pt in enumerate(points):
        x, y, tooltip = pt["x"], pt["y"], pt["tooltip"]

        # Check if we cross zero between this point and the previous
        if i > 0:
            prev = points[i - 1]
            prev_y = prev["y"]
            if (prev_y >= 0) != (y >= 0):
                # Crossing — interpolate x at y=0
                t = prev_y / (prev_y - y)
                cross_x = prev["x"] + t * (x - prev["x"])
                crossing = _make_point(cross_x, 0.0, is_crossing=True)
                green.append(crossing)
                red.append(crossing)

        # Add to the appropriate series
        point = _make_point(x, y, tooltip)
        if y >= 0:
            green.append(point)
        else:
            red.append(point)

    return green, red
