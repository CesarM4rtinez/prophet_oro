"""Constructores de graficos Plotly: candelas + WMA + señales arriba, RSI + zonas
40/60 abajo, mismo eje X compartido."""
from __future__ import annotations

from datetime import datetime

import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from .theme import COLORS, get_plotly_template

_SIGNAL_STYLE = {
    "BUY_OPEN": ("triangle-up", COLORS["bull"], "bottom center"),
    "REVERSE_TO_LONG": ("triangle-up", COLORS["bull"], "bottom center"),
    "SELL_OPEN": ("triangle-down", COLORS["bear"], "top center"),
    "REVERSE_TO_SHORT": ("triangle-down", COLORS["bear"], "top center"),
    "SL_CLOSE": ("x", COLORS["text_muted"], "top center"),
}


def strategy_chart(signals: pd.DataFrame, title: str = "", buy_level: float = 40.0, sell_level: float = 60.0) -> go.Figure:
    """Grafico combinado: velas + WMA(14) + marcadores de señal (fila superior),
    RSI(14) + lineas 40/60 (fila inferior). `signals` es el DataFrame que devuelve
    `core.strategy.generate_signals` (ya trae wma/rsi/signal calculados)."""
    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=True, row_heights=[0.7, 0.3], vertical_spacing=0.06,
        subplot_titles=(title, "RSI (14)"),
    )

    fig.add_trace(
        go.Candlestick(
            x=signals.index, open=signals["open"], high=signals["high"], low=signals["low"], close=signals["close"],
            increasing_line_color=COLORS["bull"], increasing_fillcolor=COLORS["bull"],
            decreasing_line_color=COLORS["bear"], decreasing_fillcolor=COLORS["bear"],
            line_width=1, name="Precio",
        ),
        row=1, col=1,
    )
    fig.add_trace(
        go.Scatter(x=signals.index, y=signals["wma"], mode="lines", line=dict(color=COLORS["series_forecast"], width=2), name="WMA(14)"),
        row=1, col=1,
    )

    for sig_name, (symbol, color, pos) in _SIGNAL_STYLE.items():
        rows = signals[signals["signal"] == sig_name]
        if rows.empty:
            continue
        y = rows["low"] * 0.998 if symbol == "triangle-up" else rows["high"] * 1.002
        fig.add_trace(
            go.Scatter(
                x=rows.index, y=y, mode="markers", marker=dict(symbol=symbol, size=11, color=color),
                name=sig_name, textposition=pos,
            ),
            row=1, col=1,
        )

    fig.add_trace(
        go.Scatter(x=signals.index, y=signals["rsi"], mode="lines", line=dict(color=COLORS["series_pattern"], width=1.5), name="RSI(14)"),
        row=2, col=1,
    )
    fig.add_hline(y=sell_level, line_dash="dash", line_color=COLORS["bear"], line_width=1, row=2, col=1,
                   annotation_text=f"Venta > {sell_level:g}", annotation_font_color=COLORS["bear"])
    fig.add_hline(y=buy_level, line_dash="dash", line_color=COLORS["bull"], line_width=1, row=2, col=1,
                   annotation_text=f"Compra < {buy_level:g}", annotation_font_color=COLORS["bull"])
    fig.add_hline(y=50, line_dash="dot", line_color=COLORS["text_muted"], line_width=1, row=2, col=1)

    fig.update_layout(template=get_plotly_template(), height=650, xaxis_rangeslider_visible=False, showlegend=True)
    fig.update_yaxes(range=[0, 100], row=2, col=1)
    return fig


def add_update_marker(fig: go.Figure, when: datetime | None = None) -> go.Figure:
    """Linea vertical marcando a que fecha/hora estan actualizados los datos."""
    when = when or datetime.now()
    fig.add_vline(
        x=when, line_width=1.5, line_dash="dot", line_color=COLORS["series_marker"],
        annotation_text=f"Datos al {when.strftime('%d/%m %H:%M')}",
        annotation_font_color=COLORS["series_marker"], annotation_position="top left",
        row=1, col=1,
    )
    return fig


def equity_curve_chart(equity: pd.Series, title: str = "Curva de equity") -> go.Figure:
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=equity.index, y=equity.values, mode="lines", line=dict(color=COLORS["series_hist"], width=2), name="Equity"))
    fig.update_layout(template=get_plotly_template(), title=title, height=350)
    return fig
