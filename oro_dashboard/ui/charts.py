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


def _legend_proxy(fig: go.Figure, x0, y0, color: str, name: str, symbol: str = "square") -> None:
    """Traza minima (un punto) solo para que `name`/`color` aparezcan en la leyenda,
    usada por overlays basados en `add_shape` (rectangulos), que no generan leyenda propia."""
    fig.add_trace(
        go.Scatter(
            x=[x0], y=[y0], mode="markers",
            marker=dict(color=color, size=8, symbol=symbol),
            name=name, hoverinfo="skip",
        )
    )


def add_zone_rectangles(fig: go.Figure, df: pd.DataFrame, zones: list[dict], source_df: pd.DataFrame | None = None) -> go.Figure:
    """zones: [{start_idx, end_idx, top, bottom, kind: 'bullish'|'bearish', status: 'continuo'|'fallo'|...}]

    `source_df`: si las zonas fueron detectadas en un timeframe distinto al que se
    esta graficando (ej. zonas de 1h dibujadas sobre un grafico de 5m), se usa para
    resolver los indices de las zonas a timestamps reales."""
    index_source = source_df if source_df is not None else df
    n = len(index_source.index)
    view_start, view_end = df.index[0], df.index[-1]
    for zone in zones:
        color = COLORS["bull"] if zone["kind"] == "bullish" else COLORS["bear"]
        failed = zone.get("status") == "fallo"
        x0 = index_source.index[max(0, min(zone["start_idx"], n - 1))]
        x1 = index_source.index[max(0, min(zone["end_idx"], n - 1))]
        if x1 < view_start or x0 > view_end:
            continue
        x0, x1 = max(x0, view_start), min(x1, view_end)
        fig.add_shape(
            type="rect", x0=x0, x1=x1, y0=zone["bottom"], y1=zone["top"],
            fillcolor=color, opacity=0.05 if failed else 0.14,
            line=dict(color=color, width=1, dash="dot" if failed else "solid"), layer="below",
        )

    kinds = {zone["kind"] for zone in zones}
    if "bullish" in kinds:
        _legend_proxy(fig, df.index[0], df["close"].iloc[0], COLORS["bull"], "Order Block alcista")
    if "bearish" in kinds:
        _legend_proxy(fig, df.index[0], df["close"].iloc[0], COLORS["bear"], "Order Block bajista")
    return fig


def add_bos_choch_labels(fig: go.Figure, df: pd.DataFrame, zones: list[dict], mss: dict | None = None) -> go.Figure:
    """Etiqueta los quiebres de estructura: "BOS" en cada ruptura que genero un order
    block (`zones`), y "CHoCH" en el ultimo Market Structure Shift (`mss`, de
    `label_structure`) si se provee."""
    n = len(df.index)
    for zone in zones:
        idx = max(0, min(zone["break_idx"], n - 1))
        color = COLORS["bull"] if zone["kind"] == "bullish" else COLORS["bear"]
        fig.add_annotation(
            x=df.index[idx], y=zone["broken_level"], text="BOS", showarrow=False,
            yshift=10 if zone["kind"] == "bullish" else -10, font=dict(size=9, color=color),
        )
    if mss is not None:
        idx = max(0, min(mss["idx"], n - 1))
        color = COLORS["bull"] if mss["kind"] == "alcista" else COLORS["bear"]
        fig.add_annotation(
            x=df.index[idx], y=mss["level"], text="CHoCH", showarrow=False,
            yshift=14 if mss["kind"] == "alcista" else -14,
            font=dict(size=10, color=color, family="system-ui, -apple-system, Segoe UI, sans-serif"),
            bgcolor="rgba(0,0,0,0.35)",
        )
    return fig


def add_quiebres_labels(fig: go.Figure, df: pd.DataFrame, quiebres: list[dict]) -> go.Figure:
    """quiebres: salida de core.structure_naive.own_trend — cada uno con
    idx/level/kind ('alcista'|'bajista')/tipo ('BOS'|'CHoCH'). A diferencia de
    `add_bos_choch_labels` (que etiqueta zonas/MSS del motor `core.smc_zones`),
    esta funcion etiqueta la lista de quiebres cruda del motor `own_trend`."""
    n = len(df.index)
    for q in quiebres:
        idx = max(0, min(q["idx"], n - 1))
        color = COLORS["bull"] if q["kind"] == "alcista" else COLORS["bear"]
        is_choch = q["tipo"] == "CHoCH"
        fig.add_annotation(
            x=df.index[idx], y=q["level"], text=q["tipo"], showarrow=False,
            yshift=12 if q["kind"] == "alcista" else -12,
            font=dict(size=10 if is_choch else 9, color=color, family="system-ui, -apple-system, Segoe UI, sans-serif"),
            bgcolor="rgba(0,0,0,0.35)" if is_choch else None,
        )
    return fig


def add_fvg_zones(fig: go.Figure, df: pd.DataFrame, gaps: list[dict], forward_bars: int = 15) -> go.Figure:
    """gaps: [{idx, top, bottom, kind: 'bullish'|'bearish', status: 'mitigado'|'sin_mitigar'}]"""
    n = len(df.index)
    for gap in gaps:
        color = COLORS["bull"] if gap["kind"] == "bullish" else COLORS["bear"]
        mitigated = gap.get("status") == "mitigado"
        x0 = df.index[max(0, min(gap["idx"], n - 1))]
        x1 = df.index[max(0, min(gap["idx"] + forward_bars, n - 1))]
        fig.add_shape(
            type="rect", x0=x0, x1=x1, y0=gap["bottom"], y1=gap["top"],
            fillcolor=color, opacity=0.04 if mitigated else 0.10,
            line=dict(color=color, width=1, dash="dot"), layer="below",
        )

    kinds = {gap["kind"] for gap in gaps}
    if "bullish" in kinds:
        _legend_proxy(fig, df.index[0], df["close"].iloc[0], COLORS["bull"], "FVG alcista", symbol="diamond")
    if "bearish" in kinds:
        _legend_proxy(fig, df.index[0], df["close"].iloc[0], COLORS["bear"], "FVG bajista", symbol="diamond")
    return fig


def add_liquidity_sweeps(fig: go.Figure, df: pd.DataFrame, sweeps: list[dict]) -> go.Figure:
    """sweeps: [{idx, level, kind: 'bullish'|'bearish'}] (bullish = barrida de minimos, señal alcista)"""
    if not sweeps:
        return fig
    for kind, color, symbol in (("bullish", COLORS["bull"], "x"), ("bearish", COLORS["bear"], "x")):
        points = [s for s in sweeps if s["kind"] == kind]
        if not points:
            continue
        fig.add_trace(
            go.Scatter(
                x=[df.index[s["idx"]] for s in points], y=[s["level"] for s in points], mode="markers",
                marker=dict(color=color, size=11, symbol=symbol, line=dict(width=2, color=color)),
                name=f"Barrida de liquidez {'alcista' if kind == 'bullish' else 'bajista'}",
            )
        )
    return fig


def add_fibonacci_zone(fig: go.Figure, fib: dict) -> go.Figure:
    """fib: salida de core.smc_zones.institutional_fibonacci"""
    if not fib:
        return fig
    fig.add_hrect(
        y0=fib["zone_bottom"], y1=fib["zone_top"],
        fillcolor=COLORS["series_zone"], opacity=0.08, line_width=0, layer="below",
    )
    for label, value in fib["levels"].items():
        fig.add_hline(
            y=value, line_dash="dot", line_color=COLORS["series_zone"], line_width=1,
            annotation_text=f"Fib {label}: {value:,.2f}",
            annotation_font_color=COLORS["series_zone"], annotation_position="left",
        )
    return fig


def add_structure_labels(fig: go.Figure, df: pd.DataFrame, swings: list[dict]) -> go.Figure:
    """swings: [{idx, label: 'HH'|'HL'|'LL'|'LH', price}]"""
    for swing in swings:
        is_high = swing["label"] in ("HH", "LH")
        color = COLORS["bull"] if swing["label"] in ("HH", "HL") else COLORS["bear"]
        fig.add_annotation(
            x=df.index[swing["idx"]], y=swing["price"], text=swing["label"], showarrow=False,
            yshift=14 if is_high else -14, font=dict(size=10, color=color),
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
