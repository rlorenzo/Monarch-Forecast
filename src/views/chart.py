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


def build_forecast_chart_summary(result: ForecastResult) -> str:
    """Build a screen-reader friendly summary of the forecast chart.

    The LineChart itself ships no accessible metadata, so we expose the key
    data points (start, end, low, threshold crossings, shortfalls) as a
    single descriptive string that is attached to a wrapping Semantics node.
    """
    if not result.days:
        return "Balance projection chart is empty."

    first = result.days[0]
    last = result.days[-1]
    total_days = (last.date - first.date).days + 1
    low = result.lowest_balance
    low_date = result.lowest_balance_date
    parts = [
        f"Balance projection over {total_days} days: "
        f"starts at ${result.starting_balance:,.2f} on "
        f"{first.date.strftime('%b %d')}, "
        f"ends at ${last.ending_balance:,.2f} on "
        f"{last.date.strftime('%b %d')}."
    ]
    if low_date is not None:
        parts.append(f"Lowest projected balance is ${low:,.2f} on {low_date.strftime('%b %d')}.")
    if result.safety_threshold > 0:
        if result.has_shortfall:
            first_short = result.shortfall_dates[0]
            parts.append(
                f"Drops below the ${result.safety_threshold:,.0f} safety "
                f"threshold on {first_short.strftime('%b %d')}, "
                f"{len(result.shortfall_dates)} day(s) below threshold."
            )
        else:
            parts.append(
                f"Stays above the ${result.safety_threshold:,.0f} safety "
                f"threshold for the entire window."
            )
    parts.append("See the Transactions tab for a full day-by-day text breakdown.")
    return " ".join(parts)


def build_forecast_chart(
    result: ForecastResult,
    height: float = 400,
    reduce_motion: bool = False,
) -> LineChart:
    """Create an interactive line chart with a blue balance line and green/red point coloring.

    When ``reduce_motion`` is True the balance line is drawn as straight
    segments instead of a curved spline — helpful for users who set the OS
    "reduce motion" accessibility flag and for anyone with vestibular
    sensitivity.
    """
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
        curved=not reduce_motion,
        prevent_curve_over_shooting=True,
    )

    data_series: list[LineChartData] = [balance_series]

    # Optional dashed reference line at the user's safety threshold.
    threshold = result.safety_threshold
    if threshold > 0 and result.days:
        x_start = 0
        x_end = (result.days[-1].date - start_date).days
        threshold_series = LineChartData(
            points=[
                LineChartDataPoint(
                    x=x_start,
                    y=threshold,
                    point=ChartCirclePoint(radius=0, color=_RED),
                ),
                LineChartDataPoint(
                    x=x_end,
                    y=threshold,
                    point=ChartCirclePoint(radius=0, color=_RED),
                ),
            ],
            color=ft.Colors.with_opacity(0.7, _RED),
            stroke_width=1.5,
            dash_pattern=[6, 4],
        )
        data_series.append(threshold_series)

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
                    label=ft.Text(day.date.strftime("%b %d"), size=12),
                )
            )

    all_balances = [d.ending_balance for d in result.days]
    min_bal = min(all_balances)
    max_bal = max(all_balances)
    # Pad each bound by 10% of its absolute value so the line has breathing room.
    # Using abs() ensures the padding always moves in the right direction regardless of sign.
    min_y = min(0, min_bal - abs(min_bal) * 0.1)
    max_y = max_bal + abs(max_bal) * 0.1
    # Make sure the threshold line stays visible even when it sits outside the
    # balance range (e.g. balance never drops that low).
    if threshold > 0:
        min_y = min(min_y, threshold - 50)
        max_y = max(max_y, threshold + 50)
    # Ensure non-zero vertical span (e.g. all-zero or constant-balance forecasts).
    # $200 gives a readable chart scale when the account is flat.
    if min_y == max_y:
        min_y -= 100
        max_y += 100
    y_range = max_y - min_y
    return LineChart(
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
