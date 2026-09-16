"""Constructores de graficos Plotly reutilizables, consistentes con el tema del dashboard."""
from __future__ import annotations

from datetime import datetime

import pandas as pd
import plotly.graph_objects as go

from .theme import COLORS, get_plotly_template


def _hex_to_rgba(hex_color: str, opacity: float) -> str:
    hex_color = hex_color.lstrip("#")
    r, g, b = int(hex_color[0:2], 16), int(hex_color[2:4], 16), int(hex_color[4:6], 16)
    return f"rgba({r},{g},{b},{opacity})"


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
    """Linea vertical marcando a que fecha/hora estan actualizados los datos
    graficados. `when` deberia ser la hora de Nueva York (UTC-4) del ultimo dato
    disponible (ver `core.smc_zones.to_new_york_time`), no la hora local en que
    corrio el script — si no se provee, cae de vuelta a la hora actual del sistema."""
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
                x=df.index[peak_idx],
                y=df["close"].iloc[peak_idx],
                mode="markers",
                marker=dict(color=COLORS["bear"], size=9, symbol="triangle-down"),
                name="Picos",
            )
        )
    if len(valley_idx):
        fig.add_trace(
            go.Scatter(
                x=df.index[valley_idx],
                y=df["close"].iloc[valley_idx],
                mode="markers",
                marker=dict(color=COLORS["bull"], size=9, symbol="triangle-up"),
                name="Valles",
            )
        )
    return fig


def add_pattern_lines(fig: go.Figure, df: pd.DataFrame, abcd_patterns, hs_patterns) -> go.Figure:
    for i, (x_, a_, b_, d_) in enumerate(abcd_patterns):
        idx = [x_, a_, b_, d_]
        fig.add_trace(
            go.Scatter(
                x=df.index[idx],
                y=df["close"].iloc[idx],
                mode="lines+text",
                line=dict(color=COLORS["series_pattern"], width=2, dash="dot"),
                text=["", "", "", "ABCD"],
                textposition="top center",
                textfont=dict(color=COLORS["series_pattern"]),
                name="Patron armonico ABCD",
                legendgroup="abcd",
                showlegend=(i == 0),
            )
        )
    for i, (l_, h_, r_) in enumerate(hs_patterns):
        idx = [l_, h_, r_]
        fig.add_trace(
            go.Scatter(
                x=df.index[idx],
                y=df["close"].iloc[idx],
                mode="lines+text",
                line=dict(color=COLORS["series_secondary"], width=2, dash="dot"),
                text=["", "H-C-H", ""],
                textposition="top center",
                textfont=dict(color=COLORS["series_secondary"]),
                name="Hombro-Cabeza-Hombro",
                legendgroup="hs",
                showlegend=(i == 0),
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
            y=value,
            line_dash="dash",
            line_color=color,
            line_width=1.5,
            annotation_text=f"{label}: {value:,.2f}",
            annotation_font_color=color,
            annotation_position="right",
        )
    return fig


def add_zone_rectangles(fig: go.Figure, df: pd.DataFrame, zones: list[dict], source_df: pd.DataFrame | None = None) -> go.Figure:
    """zones: [{start_idx, end_idx, top, bottom, kind: 'bullish'|'bearish', status: 'continuo'|'fallo'}]

    `source_df`: si las zonas fueron detectadas en un timeframe distinto al que se
    esta graficando (ej. zonas de 1h dibujadas sobre un grafico de 5m/15m), se usa
    para resolver los indices de las zonas a timestamps reales. Sin el, se asume que
    `zones` se detectaron sobre el mismo `df` que se esta graficando (comportamiento
    original).
    """
    index_source = source_df if source_df is not None else df
    n = len(index_source.index)
    view_start, view_end = df.index[0], df.index[-1]
    for zone in zones:
        color = COLORS["bull"] if zone["kind"] == "bullish" else COLORS["bear"]
        failed = zone.get("status") == "fallo"
        x0 = index_source.index[max(0, min(zone["start_idx"], n - 1))]
        x1 = index_source.index[max(0, min(zone["end_idx"], n - 1))]
        if x1 < view_start or x0 > view_end:
            continue  # fuera del rango visible del grafico objetivo (overlay cruzado de timeframes)
        x0, x1 = max(x0, view_start), min(x1, view_end)
        fig.add_shape(
            type="rect",
            x0=x0,
            x1=x1,
            y0=zone["bottom"],
            y1=zone["top"],
            fillcolor=color,
            opacity=0.05 if failed else 0.14,
            line=dict(color=color, width=1, dash="dot" if failed else "solid"),
            layer="below",
        )

    kinds = {zone["kind"] for zone in zones}
    if "bullish" in kinds:
        _legend_proxy(fig, df.index[0], df["close"].iloc[0], COLORS["bull"], "Order Block alcista")
    if "bearish" in kinds:
        _legend_proxy(fig, df.index[0], df["close"].iloc[0], COLORS["bear"], "Order Block bajista")
    return fig


def add_bos_choch_labels(fig: go.Figure, df: pd.DataFrame, zones: list[dict], mss: dict | None = None) -> go.Figure:
    """Etiqueta los quiebres de estructura: "BOS" en cada ruptura que genero un order
    block (`zones`, ya representan eventos de Break of Structure), y "CHoCH" en el
    ultimo Market Structure Shift (`mss`, de `label_structure`) si se provee."""
    n = len(df.index)
    for zone in zones:
        idx = max(0, min(zone["break_idx"], n - 1))
        color = COLORS["bull"] if zone["kind"] == "bullish" else COLORS["bear"]
        fig.add_annotation(
            x=df.index[idx], y=zone["broken_level"], text="BOS", showarrow=False,
            yshift=10 if zone["kind"] == "bullish" else -10,
            font=dict(size=9, color=color),
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


def add_fvg_zones(fig: go.Figure, df: pd.DataFrame, gaps: list[dict], forward_bars: int = 15) -> go.Figure:
    """gaps: [{idx, top, bottom, kind: 'bullish'|'bearish', status: 'mitigado'|'sin_mitigar'}]"""
    n = len(df.index)
    for gap in gaps:
        color = COLORS["bull"] if gap["kind"] == "bullish" else COLORS["bear"]
        mitigated = gap.get("status") == "mitigado"
        x0 = df.index[max(0, min(gap["idx"], n - 1))]
        x1 = df.index[max(0, min(gap["idx"] + forward_bars, n - 1))]
        fig.add_shape(
            type="rect",
            x0=x0,
            x1=x1,
            y0=gap["bottom"],
            y1=gap["top"],
            fillcolor=color,
            opacity=0.04 if mitigated else 0.10,
            line=dict(color=color, width=1, dash="dot"),
            layer="below",
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
                x=[df.index[s["idx"]] for s in points],
                y=[s["level"] for s in points],
                mode="markers",
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
            x=df.index[swing["idx"]], y=swing["price"],
            text=swing["label"], showarrow=False,
            yshift=14 if is_high else -14,
            font=dict(size=10, color=color),
        )
    return fig


def forecast_chart(history: pd.DataFrame, forecast: pd.DataFrame, title: str = "") -> go.Figure:
    fig = candlestick_chart(history, title)
    fig.add_trace(
        go.Scatter(
            x=forecast["ds"], y=forecast["yhat_upper"], mode="lines",
            line=dict(width=0), showlegend=False, hoverinfo="skip", name="Banda superior",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=forecast["ds"], y=forecast["yhat_lower"], mode="lines",
            line=dict(width=0), fill="tonexty", fillcolor="rgba(25,158,112,0.15)",
            name="Margen de incertidumbre (95%)", hoverinfo="skip",
        )
    )
    fig.add_trace(
        go.Scatter(
            x=forecast["ds"], y=forecast["yhat"], mode="lines",
            line=dict(color=COLORS["series_forecast"], width=2), name="Prediccion Prophet",
        )
    )
    return fig


def monte_carlo_fan_chart(times, median, bands: dict, title: str = "") -> go.Figure:
    """bands: {"95%": (lower, upper), "80%": (lower, upper), "50%": (lower, upper)}"""
    fig = _base_figure(title)
    opacities = {"95%": 0.08, "80%": 0.15, "50%": 0.25}
    for label in ["95%", "80%", "50%"]:
        if label not in bands:
            continue
        lower, upper = bands[label]
        fig.add_trace(go.Scatter(x=times, y=upper, mode="lines", line=dict(width=0), showlegend=False, hoverinfo="skip"))
        fig.add_trace(
            go.Scatter(
                x=times, y=lower, mode="lines", line=dict(width=0), fill="tonexty",
                fillcolor=f"rgba(57,135,229,{opacities[label]})", name=f"Banda {label}", hoverinfo="skip",
            )
        )
    fig.add_trace(
        go.Scatter(x=times, y=median, mode="lines", line=dict(color=COLORS["series_hist"], width=2), name="Mediana simulada")
    )
    return fig


def grouped_bar_chart(categories, series: dict, colors: dict | None = None, title: str = "", y_title: str = "Probabilidad (%)") -> go.Figure:
    fig = _base_figure(title, height=420)
    colors = colors or {}
    for label, values in series.items():
        fig.add_trace(go.Bar(name=label, x=categories, y=values, marker_color=colors.get(label, COLORS["series_hist"])))
    fig.update_layout(barmode="group", yaxis_title=y_title)
    return fig


def probability_bar_chart(labels, values, colors=None, title: str = "", y_title: str = "Probabilidad (%)") -> go.Figure:
    fig = _base_figure(title, height=400)
    fig.add_trace(
        go.Bar(
            x=labels,
            y=values,
            marker_color=colors or COLORS["series_hist"],
            text=[f"{v:.1f}%" for v in values],
            textposition="outside",
            textfont=dict(color=COLORS["text_primary"]),
        )
    )
    fig.update_layout(yaxis_title=y_title, showlegend=False)
    return fig


def equity_curve_chart(equity: pd.Series, initial_cash: float | None = None, title: str = "") -> go.Figure:
    fig = _base_figure(title)
    fig.add_trace(
        go.Scatter(
            x=equity.index, y=equity.values, mode="lines",
            line=dict(color=COLORS["series_hist"], width=2), fill="tozeroy",
            fillcolor="rgba(57,135,229,0.08)", name="Equity",
        )
    )
    if initial_cash is not None:
        fig.add_hline(
            y=initial_cash, line_dash="dot", line_color=COLORS["text_muted"], line_width=1,
            annotation_text=f"Capital inicial: {initial_cash:,.0f}", annotation_font_color=COLORS["text_muted"],
        )
    fig.update_layout(yaxis_title="Equity")
    return fig


def add_harmonic_pattern(fig: go.Figure, df: pd.DataFrame, pattern: dict) -> go.Figure:
    """Dibuja un patron armonico completado (X-A-B-C-D) como poligono relleno con
    los 5 puntos etiquetados — `pattern` viene de `core.harmonics.detect_harmonic_patterns`."""
    pts = pattern["points"]
    order = ["X", "A", "B", "C", "D"]
    xs = [df.index[pts[k]["idx"]] for k in order]
    ys = [pts[k]["price"] for k in order]
    color = COLORS["bull"] if pattern["bias"] == "alcista" else COLORS["bear"]

    fig.add_trace(
        go.Scatter(
            x=xs, y=ys, mode="lines+markers+text",
            line=dict(color=color, width=2),
            marker=dict(size=7, color=color),
            text=order, textposition="top center", textfont=dict(color=color, size=11),
            fill="toself", fillcolor=_hex_to_rgba(color, 0.12),
            name=f"{pattern['name']} {pattern['bias']} (completado)",
        )
    )
    return fig


def add_forming_pattern(fig: go.Figure, df: pd.DataFrame, pattern: dict) -> go.Figure:
    """Dibuja un patron armonico en formacion (X-A-B-C, sin D confirmado) con
    lineas punteadas y la Zona Potencial de Reversion (PRZ) proyectada para D."""
    pts = pattern["points"]
    order = ["X", "A", "B", "C"]
    xs = [df.index[pts[k]["idx"]] for k in order]
    ys = [pts[k]["price"] for k in order]
    color = COLORS["series_secondary"]

    fig.add_trace(
        go.Scatter(
            x=xs, y=ys, mode="lines+markers+text",
            line=dict(color=color, width=2, dash="dot"),
            marker=dict(size=7, color=color),
            text=order, textposition="top center", textfont=dict(color=color, size=11),
            name=f"{pattern['name']} {pattern['bias']} (formando)",
        )
    )
    x_start, x_end = df.index[pts["C"]["idx"]], df.index[-1]
    fig.add_shape(
        type="rect", x0=x_start, x1=x_end, y0=pattern["prz_bottom"], y1=pattern["prz_top"],
        fillcolor=color, opacity=0.12, line=dict(color=color, width=1, dash="dot"), layer="below",
    )
    fig.add_annotation(
        x=x_end, y=(pattern["prz_top"] + pattern["prz_bottom"]) / 2,
        text="PRZ", showarrow=False, xanchor="right",
        font=dict(size=10, color=color),
    )
    return fig


def add_support_resistance(fig: go.Figure, df: pd.DataFrame, swings: list[dict], max_levels: int = 4) -> go.Figure:
    """Lineas horizontales de soporte/resistencia a partir de los swing highs/lows
    mas recientes (`swings` viene de `core.harmonics.swing_points`)."""
    highs = sorted((p for p in swings if p["kind"] == "high"), key=lambda p: p["idx"])[-max_levels:]
    lows = sorted((p for p in swings if p["kind"] == "low"), key=lambda p: p["idx"])[-max_levels:]
    for p in highs:
        fig.add_hline(
            y=p["price"], line_dash="dash", line_width=1, line_color=COLORS["text_muted"],
            annotation_text=f"R: {p['price']:,.2f}", annotation_font_color=COLORS["text_muted"], annotation_position="left",
        )
    for p in lows:
        fig.add_hline(
            y=p["price"], line_dash="dash", line_width=1, line_color=COLORS["text_muted"],
            annotation_text=f"S: {p['price']:,.2f}", annotation_font_color=COLORS["text_muted"], annotation_position="left",
        )
    return fig


def add_auto_engine_reference_levels(fig: go.Figure, last_close: float, sl_pct: float, tp_pct: float) -> go.Figure:
    """Lineas de referencia para la vista previa del motor semi-automatico: Entry
    (ultimo cierre, compartido por ambas direcciones) y los SL/TP hipoteticos que
    resultarian de aplicar `sl_pct`/`tp_pct` sobre ese cierre, para una entrada BUY
    (linea discontinua) y una SELL (linea punteada)."""
    sl_buy, tp_buy = last_close * (1 - sl_pct / 100), last_close * (1 + tp_pct / 100)
    sl_sell, tp_sell = last_close * (1 + sl_pct / 100), last_close * (1 - tp_pct / 100)

    fig.add_hline(
        y=last_close, line_dash="solid", line_width=1.5, line_color=COLORS["text_secondary"],
        annotation_text=f"Entry (ultimo cierre): {last_close:,.2f}",
        annotation_font_color=COLORS["text_secondary"], annotation_position="right",
    )
    for value, label in [(tp_buy, "TP compra"), (sl_buy, "SL compra")]:
        color = COLORS["bull"] if value == tp_buy else COLORS["bear"]
        fig.add_hline(
            y=value, line_dash="dash", line_width=1.2, line_color=color,
            annotation_text=f"{label}: {value:,.2f}", annotation_font_color=color, annotation_position="right",
        )
    for value, label in [(tp_sell, "TP venta"), (sl_sell, "SL venta")]:
        color = COLORS["bull"] if value == tp_sell else COLORS["bear"]
        fig.add_hline(
            y=value, line_dash="dot", line_width=1.2, line_color=color,
            annotation_text=f"{label}: {value:,.2f}", annotation_font_color=color, annotation_position="left",
        )
    return fig


def add_scalping_signal_markers(fig: go.Figure, df: pd.DataFrame, scores: pd.Series, threshold: float) -> go.Figure:
    """Marca en el chart las velas donde el score historico de scalping habria
    cruzado el umbral configurado (BUY debajo de la vela, SELL encima) — vista
    previa de como se hubiera comportado la regla con el umbral actual."""
    buy_idx = scores.index[scores >= threshold]
    sell_idx = scores.index[scores <= -threshold]
    if len(buy_idx):
        fig.add_trace(
            go.Scatter(
                x=buy_idx, y=df.loc[buy_idx, "low"] * 0.999, mode="markers",
                marker=dict(symbol="triangle-up", size=10, color=COLORS["bull"]),
                name=f"Señal BUY (score >= {threshold:+.2f})",
            )
        )
    if len(sell_idx):
        fig.add_trace(
            go.Scatter(
                x=sell_idx, y=df.loc[sell_idx, "high"] * 1.001, mode="markers",
                marker=dict(symbol="triangle-down", size=10, color=COLORS["bear"]),
                name=f"Señal SELL (score <= {-threshold:+.2f})",
            )
        )
    return fig


def add_historical_setup_markers(fig: go.Figure, df: pd.DataFrame, setups: list[dict]) -> go.Figure:
    """Marca en el chart las entradas historicas que habria disparado la regla SMC
    Institucional (retest de zona con RR minimo cumplido) — `setups` viene de
    `core.smc_zones.historical_qualified_setups`."""
    buys = [s for s in setups if s["direction"] == "BUY"]
    sells = [s for s in setups if s["direction"] == "SELL"]
    if buys:
        fig.add_trace(
            go.Scatter(
                x=[df.index[s["entry_idx"]] for s in buys],
                y=[df["low"].iloc[s["entry_idx"]] * 0.999 for s in buys],
                mode="markers", marker=dict(symbol="triangle-up", size=10, color=COLORS["bull"]),
                name="Entrada BUY historica (SMC)",
            )
        )
    if sells:
        fig.add_trace(
            go.Scatter(
                x=[df.index[s["entry_idx"]] for s in sells],
                y=[df["high"].iloc[s["entry_idx"]] * 1.001 for s in sells],
                mode="markers", marker=dict(symbol="triangle-down", size=10, color=COLORS["bear"]),
                name="Entrada SELL historica (SMC)",
            )
        )
    return fig
    return fig
