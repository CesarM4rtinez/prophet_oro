"""Constructores de graficos Plotly reutilizables, consistentes con el tema del dashboard."""
from __future__ import annotations

from datetime import datetime

import pandas as pd
import plotly.graph_objects as go

from .theme import COLORS, get_plotly_template


def _base_figure(title: str = "", height: int = 560) -> go.Figure:
    fig = go.Figure()
    fig.update_layout(template=get_plotly_template(), title=title, height=height)
    return fig


def candlestick_chart(df: pd.DataFrame, title: str = "") -> go.Figure:
    fig = _base_figure(title)
    fig.add_trace(
        go.Candlestick(
            x=df.index,
            open=df["open"],
            high=df["high"],
            low=df["low"],
            close=df["close"],
            increasing_line_color=COLORS["bull"],
            increasing_fillcolor=COLORS["bull"],
            decreasing_line_color=COLORS["bear"],
            decreasing_fillcolor=COLORS["bear"],
            line_width=1,
            name="Precio",
        )
    )
    fig.update_layout(xaxis_rangeslider_visible=False)
    return fig


def add_update_marker(fig: go.Figure, when: datetime | None = None) -> go.Figure:
    """Linea vertical marcando a que fecha/hora estan actualizados los datos graficados
    (deberia ser la hora de Nueva York del ultimo dato, ver `core.timeutil.to_new_york_time`)."""
    when = when or datetime.now()
    fig.add_vline(
        x=when,
        line_width=1.5,
        line_dash="dot",
        line_color=COLORS["series_marker"],
        annotation_text=f"Datos al {when.strftime('%d/%m %H:%M')} (NY)",
        annotation_font_color=COLORS["series_marker"],
        annotation_position="top left",
    )
    return fig


def add_peaks_valleys(fig: go.Figure, df: pd.DataFrame, peak_idx, valley_idx) -> go.Figure:
    if len(peak_idx):
        fig.add_trace(
            go.Scatter(
                x=df.index[peak_idx], y=df["close"].iloc[peak_idx], mode="markers",
                marker=dict(color=COLORS["bear"], size=9, symbol="triangle-down"), name="Picos",
            )
        )
    if len(valley_idx):
        fig.add_trace(
            go.Scatter(
                x=df.index[valley_idx], y=df["close"].iloc[valley_idx], mode="markers",
                marker=dict(color=COLORS["bull"], size=9, symbol="triangle-up"), name="Valles",
            )
        )
    return fig


def add_pattern_lines(fig: go.Figure, df: pd.DataFrame, abcd_patterns, hs_patterns) -> go.Figure:
    for i, (x_, a_, b_, d_) in enumerate(abcd_patterns):
        idx = [x_, a_, b_, d_]
        fig.add_trace(
            go.Scatter(
                x=df.index[idx], y=df["close"].iloc[idx], mode="lines+text",
                line=dict(color=COLORS["series_pattern"], width=2, dash="dot"),
                text=["", "", "", "ABCD"], textposition="top center", textfont=dict(color=COLORS["series_pattern"]),
                name="Patron armonico ABCD", legendgroup="abcd", showlegend=(i == 0),
            )
        )
    for i, (l_, h_, r_) in enumerate(hs_patterns):
        idx = [l_, h_, r_]
        fig.add_trace(
            go.Scatter(
                x=df.index[idx], y=df["close"].iloc[idx], mode="lines+text",
                line=dict(color=COLORS["series_secondary"], width=2, dash="dot"),
                text=["", "H-C-H", ""], textposition="top center", textfont=dict(color=COLORS["series_secondary"]),
                name="Hombro-Cabeza-Hombro", legendgroup="hs", showlegend=(i == 0),
            )
        )
    return fig


def add_level_lines(fig: go.Figure, entry=None, stoploss=None, target1=None, target2=None) -> go.Figure:
    levels = [
        (entry, COLORS["text_secondary"], "Entry"),
        (stoploss, COLORS["bear"], "Stoploss"),
        (target1, COLORS["bull"], "Target 1"),
        (target2, COLORS["series_forecast"], "Target 2"),
    ]
    for value, color, label in levels:
        if value is None:
            continue
        fig.add_hline(
            y=value, line_dash="dash", line_color=color, line_width=1.5,
            annotation_text=f"{label}: {value:,.2f}", annotation_font_color=color, annotation_position="right",
        )
    return fig


def add_entry_sl_tp(fig: go.Figure, entrada=None, stop_loss=None, take_profit=None) -> go.Figure:
    """Como `add_level_lines` pero con etiquetas Entrada/SL/TP (un solo take-profit),
    para paneles de estructura multi-temporalidad donde no hay Target1/Target2."""
    levels = [
        (entrada, COLORS["text_secondary"], "Entrada"),
        (stop_loss, COLORS["bear"], "SL"),
        (take_profit, COLORS["bull"], "TP"),
    ]
    for value, color, label in levels:
        if value is None:
            continue
        fig.add_hline(
            y=value, line_dash="dash", line_color=color, line_width=1.5,
            annotation_text=f"{label}: {value:,.2f}", annotation_font_color=color, annotation_position="right",
        )
    return fig


def add_swing_markers(fig: go.Figure, df: pd.DataFrame) -> go.Figure:
    """Marca los swing highs/lows detectados por `core.structure_mtf.detect_swings`."""
    sh = df[df["swing_high"]]
    sl = df[df["swing_low"]]
    if len(sh):
        fig.add_trace(
            go.Scatter(x=sh.index, y=sh["high"], mode="markers", marker=dict(color=COLORS["bear"], size=8), name="Swing High")
        )
    if len(sl):
        fig.add_trace(
            go.Scatter(x=sl.index, y=sl["low"], mode="markers", marker=dict(color=COLORS["bull"], size=8), name="Swing Low")
        )
    return fig


def add_calendar_events(fig: go.Figure, events: pd.DataFrame, impacto_color: dict, y_ref: float | None = None) -> go.Figure:
    """Lineas verticales por evento economico, coloreadas por impacto (0/1/2). Solo se
    etiquetan impacto medio/alto para no amontonar texto (celdas 10 y 12)."""
    for _, ev in events.iterrows():
        color = impacto_color.get(ev["Restricciones"], COLORS["text_muted"])
        alto_impacto = ev["Restricciones"] >= 1
        fig.add_vline(
            x=ev["Fechas"], line_color=color, line_dash="dot",
            line_width=1.6 if alto_impacto else 1, opacity=0.85 if alto_impacto else 0.35,
        )
        if alto_impacto:
            fig.add_annotation(
                x=ev["Fechas"], y=1, yref="paper", showarrow=False, text=f"{ev['Descripción']} ({ev['Impacto']})",
                textangle=-90, font=dict(size=9, color=color), xanchor="left", yanchor="bottom",
            )
    return fig


def add_killzone_window(fig: go.Figure, start, end) -> go.Figure:
    fig.add_vrect(x0=start, x1=end, fillcolor=COLORS["warning"], opacity=0.12, line_width=0, annotation_text="Killzone NY")
    return fig


def probability_bar_chart(labels, values, colors=None, title: str = "", y_title: str = "Probabilidad (%)") -> go.Figure:
    fig = _base_figure(title, height=400)
    fig.add_trace(
        go.Bar(
            x=labels, y=values, marker_color=colors or COLORS["series_hist"],
            text=[f"{v:.1f}%" for v in values], textposition="outside", textfont=dict(color=COLORS["text_primary"]),
        )
    )
    fig.update_layout(yaxis_title=y_title, showlegend=False)
    return fig


def grouped_bar_chart(categories, series: dict, colors: dict | None = None, title: str = "", y_title: str = "Probabilidad (%)") -> go.Figure:
    fig = _base_figure(title, height=420)
    colors = colors or {}
    for label, values in series.items():
        fig.add_trace(go.Bar(name=label, x=categories, y=values, marker_color=colors.get(label, COLORS["series_hist"])))
    fig.update_layout(barmode="group", yaxis_title=y_title)
    return fig


def forecast_chart(history: pd.DataFrame, forecast: pd.DataFrame, title: str = "") -> go.Figure:
    fig = candlestick_chart(history, title)
    fig.add_trace(
        go.Scatter(x=forecast["ds"], y=forecast["yhat_upper"], mode="lines", line=dict(width=0), showlegend=False, hoverinfo="skip", name="Banda superior")
    )
    fig.add_trace(
        go.Scatter(
            x=forecast["ds"], y=forecast["yhat_lower"], mode="lines", line=dict(width=0), fill="tonexty",
            fillcolor="rgba(25,158,112,0.15)", name="Margen de incertidumbre (95%)", hoverinfo="skip",
        )
    )
    fig.add_trace(
        go.Scatter(x=forecast["ds"], y=forecast["yhat"], mode="lines", line=dict(color=COLORS["series_forecast"], width=2), name="Prediccion Prophet")
    )
    return fig
