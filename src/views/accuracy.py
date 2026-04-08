"""Accuracy view showing historical forecast accuracy stats and chart."""

import flet as ft
import matplotlib

matplotlib.use("agg")

from flet_charts import MatplotlibChart
from matplotlib.dates import DateFormatter
from matplotlib.figure import Figure

from src.data.history import AccuracyRecord, ForecastHistory


def build_accuracy_view(
    history: ForecastHistory,
    account_id: str,
    lookback_days: int = 30,
) -> ft.Column:
    """Build the forecast accuracy display."""
    stats = history.get_summary_stats(account_id, lookback_days)
    records = history.get_accuracy(account_id, lookback_days)

    controls: list[ft.Control] = [
        ft.Text("Forecast Accuracy", size=18, weight=ft.FontWeight.W_600),
    ]

    if stats["data_points"] == 0:
        controls.append(
            ft.Container(
                content=ft.Column(
                    [
                        ft.Icon(ft.Icons.TIMELINE, size=48, color=ft.Colors.OUTLINE),
                        ft.Text(
                            "No accuracy data yet",
                            size=16,
                            weight=ft.FontWeight.W_500,
                            color=ft.Colors.OUTLINE,
                        ),
                        ft.Text(
                            "Accuracy tracking begins after the app has been running for a few days. "
                            "Each day, your forecast is compared against the actual balance.",
                            size=13,
                            color=ft.Colors.OUTLINE,
                            text_align=ft.TextAlign.CENTER,
                            width=400,
                        ),
                    ],
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    spacing=8,
                ),
                padding=32,
                alignment=ft.alignment.center,
            )
        )
        return ft.Column(controls=controls, spacing=12)

    # Stats cards
    mae = stats["mean_abs_error"]
    mape = stats["mean_abs_pct_error"]
    grade = _accuracy_grade(mape)

    stats_row = ft.Row(
        [
            _stat_card("Accuracy Grade", grade["label"], grade["icon"], grade["color"]),
            _stat_card(
                "Avg Error",
                f"${mae:,.2f}",
                ft.Icons.STRAIGHTEN,
                ft.Colors.BLUE,
            ),
            _stat_card(
                "Avg Error %",
                f"{mape:.1f}%",
                ft.Icons.PERCENT,
                ft.Colors.BLUE,
            ),
            _stat_card(
                "Data Points",
                str(stats["data_points"]),
                ft.Icons.DATA_USAGE,
                ft.Colors.OUTLINE,
            ),
            _stat_card(
                "Max Error",
                f"${stats['max_error']:,.2f}",
                ft.Icons.WARNING_AMBER,
                ft.Colors.ORANGE,
            ),
        ],
        spacing=12,
        wrap=True,
    )
    controls.append(stats_row)

    # Accuracy chart
    if len(records) >= 2:
        chart = _build_accuracy_chart(records)
        controls.append(ft.Container(content=chart, height=300))

    return ft.Column(controls=controls, spacing=12)


def _stat_card(title: str, value: str, icon: str, color: str) -> ft.Card:
    return ft.Card(
        content=ft.Container(
            content=ft.Column(
                [
                    ft.Row(
                        [
                            ft.Icon(icon, color=color, size=18),
                            ft.Text(title, size=11, color=ft.Colors.OUTLINE),
                        ],
                        spacing=6,
                    ),
                    ft.Text(value, size=20, weight=ft.FontWeight.BOLD),
                ],
                spacing=4,
            ),
            padding=14,
            width=155,
        ),
    )


def _accuracy_grade(mape: float) -> dict:
    """Return a grade based on mean absolute percentage error."""
    if mape < 2:
        return {"label": "Excellent", "icon": ft.Icons.STAR, "color": ft.Colors.GREEN}
    if mape < 5:
        return {"label": "Good", "icon": ft.Icons.THUMB_UP, "color": ft.Colors.LIGHT_GREEN}
    if mape < 10:
        return {"label": "Fair", "icon": ft.Icons.THUMBS_UP_DOWN, "color": ft.Colors.ORANGE}
    return {"label": "Poor", "icon": ft.Icons.THUMB_DOWN, "color": ft.Colors.RED}


def _build_accuracy_chart(records: list[AccuracyRecord]) -> MatplotlibChart:
    """Build a chart comparing predicted vs actual balances."""
    fig = Figure(figsize=(8, 3), dpi=100)
    ax = fig.add_subplot(111)

    dates = [r.target_date for r in records]
    predicted = [r.predicted_balance for r in records]
    actual = [r.actual_balance for r in records]

    ax.plot(dates, actual, color="#3B82F6", linewidth=2, label="Actual", marker="o", markersize=4)
    ax.plot(
        dates,
        predicted,
        color="#F59E0B",
        linewidth=2,
        label="Predicted",
        linestyle="--",
        marker="s",
        markersize=4,
    )

    # Fill the error band
    ax.fill_between(
        dates,
        predicted,
        actual,
        alpha=0.1,
        color="#EF4444",
    )

    ax.set_ylabel("Balance ($)")
    ax.set_title("Predicted vs Actual Balance")
    ax.xaxis.set_major_formatter(DateFormatter("%b %d"))
    fig.autofmt_xdate(rotation=45)
    ax.grid(True, alpha=0.3)
    if ax.get_legend_handles_labels()[1]:
        ax.legend(loc="upper right", fontsize=8)
    fig.tight_layout()

    return MatplotlibChart(fig, expand=True)
