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

    # Color each point based on balance health
    colors = []
    for b in balances:
        if b < 0:
            colors.append("#EF4444")  # red
        elif b < threshold:
            colors.append("#F59E0B")  # amber
        else:
            colors.append("#22C55E")  # green

    fig = go.Figure()

    # Main balance line
    fig.add_trace(
        go.Scatter(
            x=dates,
            y=balances,
            mode="lines+markers",
            name="Balance",
            line={"color": "#3B82F6", "width": 2},
            marker={"color": colors, "size": 6},
            hovertemplate="<b>%{x|%b %d}</b><br>Balance: $%{y:,.2f}<extra></extra>",
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

    # Mark significant transactions
    for day in result.days:
        for txn in day.transactions:
            if abs(txn.amount) >= 500:
                symbol = "triangle-up" if txn.amount > 0 else "triangle-down"
                color = "#22C55E" if txn.amount > 0 else "#EF4444"
                fig.add_trace(
                    go.Scatter(
                        x=[day.date],
                        y=[day.ending_balance],
                        mode="markers",
                        marker={"symbol": symbol, "size": 10, "color": color},
                        name=txn.name,
                        hovertemplate=(
                            f"<b>{txn.name}</b><br>"
                            f"{'+' if txn.amount > 0 else '−'}${abs(txn.amount):,.2f}<br>"
                            f"Balance: $%{{y:,.2f}}<extra></extra>"
                        ),
                        showlegend=False,
                    )
                )

    fig.update_layout(
        title="Projected Checking Account Balance",
        yaxis_title="Balance ($)",
        xaxis_title="",
        hovermode="x unified",
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
