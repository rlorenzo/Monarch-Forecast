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
    LineChartTooltip,
)

from src.forecast.models import ForecastResult
from src.utils.money import format_money
from src.views import tokens

# CORAL_DEEP, not CORAL: the brand coral is 2.8:1 on paper and fails the 3:1
# non-text contrast floor for a data line.
_LINE = tokens.CORAL_DEEP
_THRESHOLD = tokens.SIGNAL_THRESHOLD


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
        f"starts at {format_money(result.starting_balance)} on "
        f"{first.date.strftime('%b %d')}, "
        f"ends at {format_money(last.ending_balance)} on "
        f"{last.date.strftime('%b %d')}."
    ]
    if low_date is not None:
        parts.append(
            f"Lowest projected balance is {format_money(low)} on {low_date.strftime('%b %d')}."
        )
    if result.safety_threshold > 0:
        if result.has_shortfall:
            first_short = result.shortfall_dates[0]
            parts.append(
                f"Drops below the {format_money(result.safety_threshold, cents=False)} safety "
                f"threshold on {first_short.strftime('%b %d')}, "
                f"{len(result.shortfall_dates)} day(s) below threshold."
            )
        else:
            parts.append(
                f"Stays above the {format_money(result.safety_threshold, cents=False)} safety "
                f"threshold for the entire window."
            )
    parts.append("See the Transactions tab for a full day-by-day text breakdown.")
    return " ".join(parts)


def build_forecast_chart(
    result: ForecastResult,
    height: float = 400,
    reduce_motion: bool = False,
) -> LineChart:
    """Create an interactive line chart: a 2px coral balance line, an amber dashed
    threshold line labelled at the right edge, and amber markers where the
    balance crosses the threshold.

    When ``reduce_motion`` is True the balance line is drawn as straight
    segments instead of a curved spline — helpful for users who set the OS
    "reduce motion" accessibility flag and for anyone with vestibular
    sensitivity.
    """
    if not result.days:
        return LineChart(height=height)

    start_date = result.days[0].date

    threshold = result.safety_threshold
    points = []
    prev_below: bool | None = None
    for day in result.days:
        x = (day.date - start_date).days
        # Crossing marker (6px amber circle) only where the balance moves
        # across the threshold; every other point is invisible until hovered.
        below = day.ending_balance < threshold
        crossing = threshold > 0 and prev_below is not None and below != prev_below
        prev_below = below
        points.append(
            LineChartDataPoint(
                x=x,
                y=day.ending_balance,
                tooltip=_build_tooltip_spec(day),
                show_tooltip=True,
                point=ChartCirclePoint(radius=3 if crossing else 0, color=_THRESHOLD),
                selected_point=ChartCirclePoint(radius=4, color=_LINE),
            )
        )

    balance_series = LineChartData(
        points=points,
        color=_LINE,
        stroke_width=2,
        curved=not reduce_motion,
        prevent_curve_over_shooting=True,
    )

    data_series: list[LineChartData] = [balance_series]

    # Optional 1px dashed amber reference line at the user's safety threshold
    # (labelled on the right axis below).
    if threshold > 0 and result.days:
        x_start = 0
        x_end = (result.days[-1].date - start_date).days
        threshold_series = LineChartData(
            points=[
                LineChartDataPoint(
                    x=x_start,
                    y=threshold,
                    point=ChartCirclePoint(radius=0, color=_THRESHOLD),
                ),
                LineChartDataPoint(
                    x=x_end,
                    y=threshold,
                    point=ChartCirclePoint(radius=0, color=_THRESHOLD),
                ),
            ],
            color=_THRESHOLD,
            stroke_width=1,
            dash_pattern=[6, 4],
        )
        data_series.append(threshold_series)

    # X-axis labels. The final day always gets a label — with an interval
    # that rarely divides evenly into total_days, the modulo-only approach
    # left the forecast's end date unlabeled — and a regular-interval label
    # that would land within half an interval of the end is dropped so it
    # doesn't crowd the final label.
    total_days = (result.days[-1].date - start_date).days
    label_interval = max(total_days // 6, 1)
    x_labels = []
    for day in result.days:
        day_offset = (day.date - start_date).days
        if day_offset == total_days:
            continue
        if day_offset % label_interval == 0 and total_days - day_offset >= label_interval / 2:
            x_labels.append(
                ChartAxisLabel(
                    value=day_offset,
                    label=_axis_text(day.date.strftime("%b %d")),
                )
            )
    x_labels.append(
        ChartAxisLabel(
            value=total_days,
            label=_axis_text(result.days[-1].date.strftime("%b %d")),
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
    # Right-edge threshold label: an axis label pinned to the threshold's y.
    right_axis = None
    if threshold > 0:
        right_axis = ChartAxis(
            labels=[
                ChartAxisLabel(
                    value=threshold,
                    label=_axis_text(
                        f"Threshold {format_money(threshold, cents=False)}",
                        tokens.SIGNAL_THRESHOLD_INK,
                    ),
                )
            ],
            label_size=110,
        )
    return LineChart(
        data_series=data_series,
        interactive=True,
        tooltip=LineChartTooltip(
            bgcolor=tokens.PAPER,
            border_radius=6,
            border_side=ft.BorderSide(1, tokens.RULE),
            padding=ft.Padding.symmetric(horizontal=12, vertical=8),
        ),
        # No min/max labels: the padded bounds are arbitrary values
        # (e.g. -643.3) that collide with the nearest interval label.
        left_axis=ChartAxis(
            title=_axis_text("Balance ($)"),
            label_size=60,
            show_min=False,
            show_max=False,
        ),
        right_axis=right_axis,
        bottom_axis=ChartAxis(
            labels=x_labels,
            label_size=30,
        ),
        horizontal_grid_lines=ChartGridLines(
            interval=max(y_range / 5, 1),
            color=tokens.RULE,
            width=1,
        ),
        min_y=min_y,
        max_y=max_y,
        height=height,
        expand=True,
    )


def _axis_text(value: str, color: str = tokens.INK_3) -> ft.Text:
    """Axis text: 11pt Inter, ink-3 (the Label floor, no uppercase for dates)."""
    style = tokens.label_style(color)
    style.letter_spacing = 0
    return ft.Text(value, style=style)


def _build_tooltip_spec(day) -> LineChartDataPointTooltip:
    """Tooltip content: date in the serif headline role, balance in figures,
    delta on its own line in signal color with an explicit +/\u2212 glyph."""
    date_style = tokens.title_style(tokens.INK)
    date_style.font_family = tokens.FONT_DISPLAY
    balance_style = tokens.figure_secondary_style(tokens.INK)
    spans = [
        ft.TextSpan(day.date.strftime("%b %d") + "\n", style=date_style),
        ft.TextSpan(format_money(day.ending_balance), style=balance_style),
    ]
    if day.transactions:
        delta_color = tokens.SIGNAL_POSITIVE if day.net_change >= 0 else tokens.SIGNAL_NEGATIVE
        spans.append(
            ft.TextSpan(
                "\n" + format_money(day.net_change, signed=True),
                style=tokens.body_style(delta_color),
            )
        )
        for txn in day.transactions[:4]:
            spans.append(
                ft.TextSpan(
                    f"\n{format_money(txn.amount, signed=True, cents=False)} {txn.name[:18]}",
                    style=tokens.label_style(tokens.INK_2),
                )
            )
        if len(day.transactions) > 4:
            spans.append(
                ft.TextSpan(
                    f"\n+{len(day.transactions) - 4} more",
                    style=tokens.label_style(tokens.INK_3),
                )
            )
    return LineChartDataPointTooltip(
        text="", text_style=tokens.body_style(tokens.INK), text_spans=spans
    )


def _build_tooltip(day) -> str:
    """Plain-text form of the tooltip (kept for tests and text fallbacks)."""
    lines = [f"{day.date.strftime('%b %d')}: {format_money(day.ending_balance)}"]
    for txn in day.transactions[:4]:
        lines.append(f"{format_money(txn.amount, signed=True, cents=False)} {txn.name[:18]}")
    if len(day.transactions) > 4:
        lines.append(f"...+{len(day.transactions) - 4} more")
    if len(day.transactions) > 1:
        lines.append(f"Net: {format_money(day.net_change, signed=True, cents=False)}")
    return "\n".join(lines)
