"""Balance timeline chart using matplotlib rendered as a static image."""

import base64
import io

import flet as ft
from matplotlib.dates import DateFormatter, WeekdayLocator
from matplotlib.figure import Figure

from src.forecast.models import ForecastResult


def build_forecast_chart(
    result: ForecastResult,
    width: float = 800,
    height: float = 400,
) -> ft.Image:
    """Create a matplotlib chart rendered as a base64 PNG image."""
    fig = Figure(figsize=(width / 100, height / 100), dpi=150)
    ax = fig.add_subplot(111)

    dates = [day.date for day in result.days]
    balances = [day.ending_balance for day in result.days]
    threshold = result.safety_threshold

    # Color the line segments based on balance health
    for i in range(len(dates) - 1):
        segment_dates = [dates[i], dates[i + 1]]
        segment_balances = [balances[i], balances[i + 1]]

        if balances[i + 1] < 0:
            color = "#EF4444"  # red
        elif balances[i + 1] < threshold:
            color = "#F59E0B"  # amber
        else:
            color = "#22C55E"  # green

        ax.plot(segment_dates, segment_balances, color=color, linewidth=2)

    # Threshold line
    if threshold > 0:
        ax.axhline(
            y=threshold,
            color="#F59E0B",
            linestyle="--",
            linewidth=1,
            alpha=0.7,
            label=f"Safety threshold (${threshold:,.0f})",
        )

    # Zero line
    ax.axhline(y=0, color="#EF4444", linestyle="-", linewidth=0.8, alpha=0.5)

    # Fill below zero in red
    ax.fill_between(
        dates,
        balances,
        0,
        where=[b < 0 for b in balances],
        alpha=0.15,
        color="#EF4444",
        interpolate=True,
    )

    # Mark income and large expense transactions
    for day in result.days:
        for txn in day.transactions:
            if abs(txn.amount) >= 100:
                marker = "^" if txn.amount > 0 else "v"
                color = "#22C55E" if txn.amount > 0 else "#EF4444"
                ax.plot(day.date, day.ending_balance, marker=marker, color=color, markersize=6)

    ax.set_xlabel("")
    ax.set_ylabel("Balance ($)")
    ax.set_title("Projected Checking Account Balance")
    ax.xaxis.set_major_formatter(DateFormatter("%b %d"))
    ax.xaxis.set_major_locator(WeekdayLocator(byweekday=0))
    fig.autofmt_xdate(rotation=45)
    ax.grid(True, alpha=0.3)
    if ax.get_legend_handles_labels()[1]:
        ax.legend(loc="upper right", fontsize=8)
    fig.tight_layout()

    return _fig_to_image(fig, height=height)


def _fig_to_image(fig: Figure, height: float = 400) -> ft.Image:
    """Render a matplotlib Figure to a Flet Image via base64 PNG."""
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight", facecolor="white")
    buf.seek(0)
    img_b64 = base64.b64encode(buf.read()).decode()
    return ft.Image(
        src=f"data:image/png;base64,{img_b64}",
        fit=ft.BoxFit.CONTAIN,
        height=height,
    )
