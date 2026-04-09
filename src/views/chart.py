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


def build_forecast_chart(
    result: ForecastResult,
    height: float = 400,
) -> LineChart:
    """Create an interactive line chart with hover tooltips showing transactions."""
    if not result.days:
        return LineChart(height=height)

    threshold = result.safety_threshold
    start_date = result.days[0].date

    # Build data points with tooltips
    points = []
    for day in result.days:
        x = (day.date - start_date).days

        # Build concise tooltip — keep short to avoid truncation
        lines = [f"{day.date.strftime('%b %d')} — ${day.ending_balance:,.2f}"]
        for txn in day.transactions[:4]:  # Limit to 4 transactions
            sign = "+" if txn.amount > 0 else "-"
            name = txn.name[:20]
            lines.append(f"{sign}${abs(txn.amount):,.0f} {name}")
        if len(day.transactions) > 4:
            lines.append(f"...+{len(day.transactions) - 4} more")
        if day.transactions:
            lines.append(f"Net: ${day.net_change:+,.0f}")
        tooltip_text = "\n".join(lines)

        # Color based on health
        if day.ending_balance < 0:
            color = ft.Colors.RED
        elif day.ending_balance < threshold:
            color = ft.Colors.ORANGE
        else:
            color = ft.Colors.BLUE

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

    # Main balance line
    balance_series = LineChartData(
        points=points,
        color=ft.Colors.BLUE,
        stroke_width=2.5,
        curved=True,
        prevent_curve_over_shooting=True,
        below_line_bgcolor=ft.Colors.with_opacity(0.05, ft.Colors.BLUE),
    )

    # X-axis labels (show ~6 evenly spaced dates)
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

    chart = LineChart(
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
            interval=max(abs(max(d.ending_balance for d in result.days)) / 5, 1),
            color=ft.Colors.with_opacity(0.15, ft.Colors.ON_SURFACE),
        ),
        min_y=min(0, min(d.ending_balance for d in result.days) * 1.1),
        max_y=max(d.ending_balance for d in result.days) * 1.1,
        height=height,
        expand=True,
    )

    return chart
