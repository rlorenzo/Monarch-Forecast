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

# Accessible colors with good contrast
_BLUE = "#1976D2"
_GREEN = "#2E7D32"
_RED = "#C62828"


def build_forecast_chart(
    result: ForecastResult,
    height: float = 400,
) -> LineChart:
    """Create an interactive line chart with a blue balance line and green/red point coloring."""
    if not result.days:
        return LineChart(height=height)

    start_date = result.days[0].date

    points = []
    for day in result.days:
        x = (day.date - start_date).days
        tooltip_text = _build_tooltip(day)
        color = _GREEN if day.ending_balance >= 0 else _RED

        points.append(
            LineChartDataPoint(
                x=x,
                y=day.ending_balance,
                tooltip=LineChartDataPointTooltip(
                    text=tooltip_text,
                    text_style=ft.TextStyle(
                        color=ft.Colors.WHITE,
                        size=11,
                        weight=ft.FontWeight.W_500,
                    ),
                ),
                show_tooltip=True,
                point=ChartCirclePoint(radius=3, color=color),
                selected_point=ChartCirclePoint(radius=5, color=color),
            )
        )

    # Single data series with blue line; points colored green/red
    balance_series = LineChartData(
        points=points,
        color=_BLUE,
        stroke_width=2.5,
        curved=True,
        prevent_curve_over_shooting=True,
    )

    # X-axis labels
    total_days = (result.days[-1].date - start_date).days
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
    min_y = min(0, min(all_balances) * 1.1)
    max_y = max(all_balances) * 1.1
    # Ensure non-zero vertical span so the chart renders correctly when all balances are equal
    if min_y == max_y:
        min_y -= 100
        max_y += 100
    y_range = max_y - min_y
    return LineChart(
        data_series=[balance_series],
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
            interval=max(y_range / 5, 1),
            color=ft.Colors.with_opacity(0.15, ft.Colors.ON_SURFACE),
        ),
        min_y=min_y,
        max_y=max_y,
        height=height,
        expand=True,
    )


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
