"""Balance timeline chart using Plotly for interactive visualization."""

import plotly.graph_objects as go
from flet_charts import PlotlyChart

from src.forecast.models import ForecastResult


def build_forecast_chart(
    result: ForecastResult,
    height: float = 400,
) -> PlotlyChart:
    """Create an interactive Plotly chart showing the balance forecast timeline."""
    dates = [day.date for day in result.days]
    balances = [day.ending_balance for day in result.days]
    threshold = result.safety_threshold

    # Build hover text showing each day's transactions
    hover_texts = []
    for day in result.days:
        parts = [f"<b>{day.date.strftime('%b %d, %Y')}</b>"]
        parts.append(f"Balance: <b>${day.ending_balance:,.2f}</b>")
        if day.transactions:
            parts.append("")
            for txn in day.transactions:
                sign = "+" if txn.amount > 0 else "−"
                color = "green" if txn.amount > 0 else "red"
                parts.append(
                    f"<span style='color:{color}'>{sign}${abs(txn.amount):,.2f}</span> {txn.name}"
                )
            parts.append(f"<br>Net change: <b>${day.net_change:+,.2f}</b>")
        hover_texts.append("<br>".join(parts))

    # Color each point based on balance health
    colors = []
    for b in balances:
        if b < 0:
            colors.append("#EF4444")
        elif b < threshold:
            colors.append("#F59E0B")
        else:
            colors.append("#22C55E")

    fig = go.Figure()

    # Main balance line
    fig.add_trace(
        go.Scatter(
            x=dates,
            y=balances,
            mode="lines+markers",
            name="Balance",
            line={"color": "#3B82F6", "width": 2.5},
            marker={"color": colors, "size": 7},
            hovertext=hover_texts,
            hoverinfo="text",
            fill="tozeroy",
            fillcolor="rgba(59, 130, 246, 0.05)",
        )
    )

    # Threshold line
    if threshold > 0:
        fig.add_hline(
            y=threshold,
            line_dash="dash",
            line_color="#F59E0B",
            annotation_text=f"Safety: ${threshold:,.0f}",
            annotation_position="top right",
            annotation_font_color="#F59E0B",
        )

    # Zero line
    fig.add_hline(y=0, line_color="#EF4444", line_width=0.8, opacity=0.5)

    fig.update_layout(
        title="Projected Checking Account Balance",
        yaxis_title="Balance ($)",
        xaxis_title="",
        hovermode="closest",
        showlegend=False,
        margin={"l": 60, "r": 20, "t": 40, "b": 40},
        height=height,
        yaxis_tickformat="$,.0f",
        xaxis_tickformat="%b %d",
        plot_bgcolor="white",
        xaxis={"gridcolor": "#f0f0f0", "showgrid": True},
        yaxis={"gridcolor": "#f0f0f0", "showgrid": True},
    )

    return PlotlyChart(figure=fig, expand=True)
