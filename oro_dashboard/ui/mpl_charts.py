"""Graficos matplotlib que replican EXACTAMENTE el estilo de proyecciones_oro.ipynb
(celdas 13/15 - Probabilidad Condicional de Targets por Patron, compra/venta) y de
proyecciones_oro_estructura.ipynb (Estructura Multi-Temporalidad 5m/15m/1h).

Se usan a proposito graficos matplotlib (no Plotly como el resto de `ui/charts.py`):
el usuario quiere ver en el dashboard la misma identidad visual que ya conoce de esas
celdas del notebook, no una reinterpretacion con otra libreria."""
from __future__ import annotations

from datetime import datetime

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.patches import Rectangle

MESES_ES = {
    1: "ene", 2: "feb", 3: "mar", 4: "abr", 5: "may", 6: "jun",
    7: "jul", 8: "ago", 9: "sep", 10: "oct", 11: "nov", 12: "dic",
}


def _format_x_axis(ax, index: pd.DatetimeIndex, n_ticks: int = 6) -> None:
    n = len(index)
    step = max(1, n // n_ticks)
    positions = list(range(0, n, step))
    ticks = [index[i] for i in positions]
    labels = [f"{t.day:02d} {MESES_ES[t.month]} {t.strftime('%H:%M')}" for t in ticks]
    ax.set_xticks(ticks)
    ax.set_xticklabels(labels, rotation=45, ha="right", fontsize=8)
    ax.set_xlabel(f"Fecha y hora ({index.tz})", fontsize=8)


def targets_price_chart(
    df: pd.DataFrame,
    entry: float,
    stoploss: float,
    target1: float,
    target2: float,
    updated_at_label: str,
    symbol_label: str,
    direction_label: str,
    entry_label: str = "Entry",
) -> plt.Figure:
    """Precio + Entry/Stoploss/Target1/Target2 (celda 13 = compra, celda 15 = venta)."""
    with plt.style.context("dark_background"):
        fig, ax = plt.subplots(figsize=(11, 5.5))
        ax.plot(df.index, df["close"], color="#00bfff", linewidth=1.2, label=symbol_label)
        ax.axhline(entry, color="#3d7dff", linestyle="--", label=f"{entry_label}: {entry:,.2f}")
        ax.axhline(stoploss, color="#ff4d4d", linestyle="--", label=f"Stoploss: {stoploss:,.2f}")
        ax.axhline(target1, color="#33d17a", linestyle="--", label=f"Target 1: {target1:,.2f}")
        ax.axhline(target2, color="#33d17a", linestyle="--", label=f"Target 2: {target2:,.2f}")
        ax.axvline(df.index[-1], color="magenta", linestyle=":", linewidth=1.5, zorder=5,
                   label=f"Actualizado: {updated_at_label}")
        
        ax.set_title(
            f"{symbol_label} - Probabilidad Condicional de Targets por Patron — {direction_label} (15m)",
            fontsize=13, fontweight="bold",
        )
        ax.set_xlabel(f"Fecha y hora ({df.index.tz})")
        ax.set_ylabel("Precio (USD)")
        ax.legend(fontsize=8, loc="upper left")
        ax.grid(alpha=0.3)
        fig.autofmt_xdate(rotation=30, ha="right")
        fig.tight_layout()
    return fig


def structure_smc_chart(
    df_structure: pd.DataFrame,
    zones: list[dict],
    sweeps: list[dict],
    symbol_label: str,
    structure_interval_label: str,
    macro_bias: str,
    window: int = 200,
) -> plt.Figure:
    """Estructura SMC de una sola temporalidad: Order Blocks (zonas sombreadas) y
    barridas de liquidez (marcador 'x'), con el sesgo diario en el titulo — replica
    la celda "Estrategia Institucional SMC" de proyecciones_oro_prophet.ipynb."""
    with plt.style.context("dark_background"):
        fig, ax = plt.subplots(figsize=(13, 6.5))
        reciente = df_structure.tail(window)
        ax.plot(reciente.index, reciente["close"], color="#00bfff", linewidth=1.2, label=symbol_label)

        corte = len(df_structure) - window
        labeled_zone_kinds = set()
        for zone in zones:
            if zone["end_idx"] < corte:
                continue
            x0 = df_structure.index[max(0, zone["start_idx"])]
            x1 = df_structure.index[min(zone["end_idx"], len(df_structure) - 1)]
            color = "lime" if zone["kind"] == "bullish" else "red"
            alpha = 0.06 if zone["status"] == "fallo" else 0.16
            label = None
            if zone["kind"] not in labeled_zone_kinds:
                label = f"Order Block {'alcista' if zone['kind'] == 'bullish' else 'bajista'}"
                labeled_zone_kinds.add(zone["kind"])
            ax.axvspan(x0, x1, color=color, alpha=alpha, label=label)

            prob = zone.get("prob")
            if prob is not None:
                is_bullish = zone["kind"] == "bullish"
                ax.annotate(
                    f"{prob['probability']:.0f}%",
                    xy=(x1, zone["top"] if is_bullish else zone["bottom"]),
                    xytext=(0, 5 if is_bullish else -5), textcoords="offset points",
                    fontsize=8, fontweight="bold", color=color,
                    ha="right", va="bottom" if is_bullish else "top",
                )

        labeled_sweep_kinds = set()
        for sweep in sweeps:
            if sweep["idx"] < corte:
                continue
            t = df_structure.index[sweep["idx"]]
            color = "red" if sweep["kind"] == "bearish" else "lime"
            label = None
            if sweep["kind"] not in labeled_sweep_kinds:
                label = f"Barrida {'alcista' if sweep['kind'] == 'bullish' else 'bajista'}"
                labeled_sweep_kinds.add(sweep["kind"])
            ax.scatter([t], [sweep["level"]], color=color, marker="x", s=100, zorder=5, label=label)

        ax.set_title(
            f"{symbol_label} - Estructura SMC ({structure_interval_label}) - "
            f"Sesgo diario: {macro_bias.upper()}",
            fontsize=14, fontweight="bold",
        )
        ax.legend(loc="upper left", fontsize=8)
        ax.grid(alpha=0.3)
        fig.autofmt_xdate(rotation=45, ha="right")
        fig.tight_layout()
    return fig


def structure_multi_timeframe_chart(
    panels: list[dict],
    symbol_label: str,
    veredicto: str | None,
    alineadas: int = 0,
    divergentes: list[str] | None = None,
) -> plt.Figure:
    """3 paneles apilados (uno por temporalidad), cada uno con su tendencia vigente,
    swings marcados, marcadores BOS/CHoCH en cada quiebre de estructura, y sus propias
    lineas de Entrada/SL/TP.

    `panels`: [{"label": "1h"/"15m"/"5m", "df": DataFrame con columnas close/high/low/
    swing_high/swing_low, "kind": "bullish"/"bearish"/None, "entry": float|None,
    "sl": float|None, "tp": float|None, "breaks": [{"time", "level", "kind", "tipo":
    "BOS"|"CHoCH"}, ...] ya recortados a las velas mostradas}]
    """
    with plt.style.context("dark_background"):
        fig, axes = plt.subplots(len(panels), 1, figsize=(11, 4.3 * len(panels)))
        if len(panels) == 1:
            axes = [axes]

        for ax, panel in zip(axes, panels):
            df_tf = panel["df"]
            kind = panel.get("kind")
            trend_label = {"bullish": "ALCISTA", "bearish": "BAJISTA"}.get(kind, "SIN DATO")
            color_trend = {"bullish": "lime", "bearish": "red"}.get(kind, "gray")

            ax.plot(df_tf.index, df_tf["close"], color="#00bfff", linewidth=1.1, label=symbol_label)
            swing_high = df_tf[df_tf["swing_high"]]
            swing_low = df_tf[df_tf["swing_low"]]
            ax.scatter(swing_high.index, swing_high["high"], color="red", s=22, zorder=5, label="Swing High")
            ax.scatter(swing_low.index, swing_low["low"], color="lime", s=22, zorder=5, label="Swing Low")

            # CHoCH = quiebre en contra de la tendencia previa (posible entrada temprana
            # en la nueva direccion); BOS = quiebre a favor de la tendencia vigente
            # (solo confirma que sigue viva, no es una señal nueva).
            bos_labeled = choch_labeled = False
            for brk in panel.get("breaks", []):
                is_choch = brk["tipo"] == "CHoCH"
                color = "yellow" if is_choch else ("lime" if brk["kind"] == "alcista" else "red")
                marker = "*" if is_choch else "^" if brk["kind"] == "alcista" else "v"
                size = 160 if is_choch else 70
                label = None
                if is_choch and not choch_labeled:
                    label, choch_labeled = "CHoCH (cambio de estructura)", True
                elif not is_choch and not bos_labeled:
                    label, bos_labeled = "BOS (continuacion)", True
                ax.scatter(
                    [brk["time"]], [brk["level"]], color=color, marker=marker, s=size,
                    zorder=6, edgecolors="white" if is_choch else "none", linewidths=0.8, label=label,
                )

            ax.set_title(
                f"{panel['label']} — tendencia vigente: {trend_label}",
                color=color_trend, fontsize=12, fontweight="bold",
            )

            if panel.get("entry") is not None:
                ax.axhline(panel["entry"], color="blue", linestyle="--", linewidth=1.2,
                           label=f"Entrada: {panel['entry']:,.2f}")
            if panel.get("sl") is not None:
                ax.axhline(panel["sl"], color="red", linestyle="--", linewidth=1.2,
                           label=f"SL: {panel['sl']:,.2f}")
            if panel.get("tp") is not None:
                ax.axhline(panel["tp"], color="lime", linestyle="--", linewidth=1.2,
                           label=f"TP: {panel['tp']:,.2f}")

            ax.legend(fontsize=7, loc="upper left", ncol=2)
            ax.grid(alpha=0.3)
            _format_x_axis(ax, df_tf.index)

        if veredicto is None:
            div_txt = f" (diverge: {', '.join(divergentes)})" if divergentes else ""
            titulo_veredicto = f"SIN CONFIRMACION — no operar{div_txt}"
        else:
            titulo_veredicto = f"SENAL {veredicto.upper()} ({alineadas}/3)"
        fig.suptitle(
            f"{symbol_label} — Estructura Multi-Temporalidad (5m / 15m / 1h) — {titulo_veredicto}",
            fontsize=15, fontweight="bold",
        )
        fig.tight_layout()
    return fig


def mtf_zone_chart(
    df: pd.DataFrame,
    swings: pd.DataFrame,
    breaks: list[dict],
    trend: str | None,
    symbol_label: str,
    interval_label: str,
    role_label: str,
    position: dict | None = None,
    position_confirmed: bool = False,
    max_zones: int = 6,
    window: int = 200,
    forward_bars: int = 20,
) -> plt.Figure:
    """Precio + zonas horizontales de estructura (rectangulos, no lineas ni texto
    suelto) para el panel BI de direccion 15m / entrada 5m: cada quiebre reciente
    se dibuja como una zona que va desde el swing que la origino hasta la vela
    que la rompio (BOS = borde discontinuo, CHoCH = borde solido y mas opaco, es
    el cambio de estructura). Si se pasa `position` (salida de
    `core.mtf_signal._build_position`), se agrega ademas la "posicion" larga
    (verde) o corta (roja) proyectada desde el quiebre disparador hacia adelante
    -zona de beneficio (entrada→TP) y zona de riesgo (entrada→SL)-, con trazo
    solido si `position_confirmed` (señal completa) o discontinuo/mas tenue si
    es solo una vista previa (todavia no cumple las 4 reglas)."""
    with plt.style.context("dark_background"):
        fig, ax = plt.subplots(figsize=(12, 6))
        reciente = df.tail(window)
        corte = len(df) - len(reciente)
        swings_reciente = swings.tail(window)

        ax.plot(reciente.index, reciente["close"], color="#00bfff", linewidth=1.1, label=symbol_label, zorder=2)
        sh = swings_reciente[swings_reciente["swing_high"]]
        sl_pts = swings_reciente[swings_reciente["swing_low"]]
        ax.scatter(sh.index, sh["high"], color="red", s=16, zorder=3, label="Swing High", alpha=0.7)
        ax.scatter(sl_pts.index, sl_pts["low"], color="lime", s=16, zorder=3, label="Swing Low", alpha=0.7)

        price_span = reciente["high"].max() - reciente["low"].min()
        band = max(price_span * 0.018, 1e-6)
        visible_breaks = [b for b in breaks if b["idx"] >= corte][-max_zones:]
        for brk in visible_breaks:
            swing_idx = brk.get("swing_idx", brk["idx"])
            x0 = df.index[max(0, swing_idx)]
            x1 = df.index[min(brk["idx"], len(df) - 1)]
            if x1 <= x0:
                continue
            color = "lime" if brk["kind"] == "alcista" else "red"
            is_choch = brk["tipo"] == "CHoCH"
            ax.add_patch(
                Rectangle(
                    (x0, brk["level"] - band / 2), x1 - x0, band,
                    facecolor=color, edgecolor=color, alpha=0.4 if is_choch else 0.2,
                    linewidth=1.4 if is_choch else 0.9, linestyle="-" if is_choch else "--",
                    zorder=2.5,
                    label=f"Zona {brk['tipo']} {'alcista' if brk['kind'] == 'alcista' else 'bajista'}",
                )
            )

        x_right = reciente.index[-1]
        if position is not None:
            entry, sl, tp, direction = position["entry"], position["sl"], position["tp"], position["direction"]
            trigger = position.get("trigger")
            freq = df.index[1] - df.index[0] if len(df) > 1 else pd.Timedelta(minutes=5)
            trigger_idx = trigger["idx"] if trigger is not None else len(df) - 1
            x0 = df.index[min(max(0, trigger_idx), len(df) - 1)]
            x1 = df.index[-1] + forward_bars * freq
            x_right = x1
            solid = position_confirmed
            reward_lo, reward_hi = sorted([entry, tp])
            risk_lo, risk_hi = sorted([entry, sl])
            pos_label = "LARGO" if direction == "BUY" else "CORTO"
            ax.add_patch(
                Rectangle(
                    (x0, reward_lo), x1 - x0, reward_hi - reward_lo,
                    facecolor="lime", alpha=0.28 if solid else 0.12, edgecolor="lime",
                    linewidth=1.6 if solid else 1.0, linestyle="-" if solid else "--",
                    zorder=4, label=f"Zona de beneficio ({pos_label})",
                )
            )
            ax.add_patch(
                Rectangle(
                    (x0, risk_lo), x1 - x0, risk_hi - risk_lo,
                    facecolor="red", alpha=0.28 if solid else 0.12, edgecolor="red",
                    linewidth=1.6 if solid else 1.0, linestyle="-" if solid else "--",
                    zorder=4, label="Zona de riesgo",
                )
            )
            ax.axhline(entry, color="white", linestyle=":", linewidth=1.2, zorder=5, label=f"Entrada: {entry:,.2f}")
            ax.axhline(tp, color="lime", linestyle="--", linewidth=1.2, zorder=5, label=f"TP: {tp:,.2f}")
            ax.axhline(sl, color="red", linestyle="--", linewidth=1.2, zorder=5, label=f"SL: {sl:,.2f}")

        trend_label = {"alcista": "ALCISTA", "bajista": "BAJISTA"}.get(trend, "SIN DATO")
        color_trend = {"alcista": "lime", "bajista": "red"}.get(trend, "gray")
        status_txt = ""
        if position is not None:
            estado = "SEÑAL CONFIRMADA" if position_confirmed else "posición proyectada (vista previa)"
            status_txt = f" — {estado} ({'LARGO' if position['direction'] == 'BUY' else 'CORTO'})"
        ax.set_title(
            f"{symbol_label} — {role_label} ({interval_label}) — tendencia: {trend_label}{status_txt}",
            color=color_trend, fontsize=12, fontweight="bold",
        )
        ax.set_ylabel("Precio (USD)")
        ax.set_xlim(reciente.index[0], x_right)
        handles, labels = ax.get_legend_handles_labels()
        by_label = dict(zip(labels, handles))
        ax.legend(by_label.values(), by_label.keys(), fontsize=7.5, loc="upper left", ncol=2)
        ax.grid(alpha=0.3)
        fig.autofmt_xdate(rotation=30, ha="right")
        fig.tight_layout()
    return fig


def equity_trades_chart(trades: list[dict], equity: list[float], initial_capital: float, symbol_label: str) -> plt.Figure:
    """Panel de equity + P/L por trade, al estilo de los reportes de backtest
    (curva de capital arriba, resultado de cada trade abajo)."""
    with plt.style.context("dark_background"):
        fig, (ax_eq, ax_pnl) = plt.subplots(
            2, 1, figsize=(12, 7), sharex=True, gridspec_kw={"height_ratios": [2, 1]},
        )
        exit_times = [t["exit_time"] for t in trades]
        pnl_pct = [t["pnl_pct"] * 100 for t in trades]

        ax_eq.plot(exit_times, equity, color="#3d7dff", linewidth=1.4, label="Capital")
        ax_eq.axhline(initial_capital, color="#898781", linestyle="--", linewidth=1, label=f"Capital inicial: ${initial_capital:,.0f}")
        ax_eq.set_title(f"{symbol_label} — Curva de Capital y P/L por Trade", fontsize=13, fontweight="bold")
        ax_eq.set_ylabel("Capital (USD)")
        ax_eq.legend(fontsize=8, loc="upper left")
        ax_eq.grid(alpha=0.3)

        colors = ["#0ca30c" if p > 0 else "#d03b3b" for p in pnl_pct]
        ax_pnl.scatter(exit_times, pnl_pct, color=colors, s=26, zorder=5)
        ax_pnl.axhline(0, color="#898781", linewidth=1)
        ax_pnl.set_ylabel("P/L por trade (%)")
        ax_pnl.set_xlabel("Cierre del trade")
        ax_pnl.grid(alpha=0.3)
        fig.autofmt_xdate(rotation=30, ha="right")
        fig.tight_layout()
    return fig


def price_with_trades_chart(df: pd.DataFrame, trades: list[dict], symbol_label: str) -> plt.Figure:
    """Precio + marcadores de entrada (compra, triangulo verde) y salida (venta,
    triangulo rojo) de cada trade simulado, con volumen debajo."""
    with plt.style.context("dark_background"):
        fig, (ax_price, ax_vol) = plt.subplots(
            2, 1, figsize=(12, 7), sharex=True, gridspec_kw={"height_ratios": [3, 1]},
        )
        ax_price.plot(df.index, df["close"], color="#00bfff", linewidth=1.0, label=symbol_label)

        entry_times = [t["entry_time"] for t in trades]
        entry_prices = [t["entry_price"] for t in trades]
        exit_times = [t["exit_time"] for t in trades]
        exit_prices = [t["exit_price"] for t in trades]
        ax_price.scatter(entry_times, entry_prices, marker="^", color="lime", s=45, zorder=5, label="Entrada")
        ax_price.scatter(exit_times, exit_prices, marker="v", color="red", s=45, zorder=5, label="Salida")

        ax_price.set_title(f"{symbol_label} — Precio con Entradas/Salidas Simuladas", fontsize=13, fontweight="bold")
        ax_price.set_ylabel("Precio (USD)")
        ax_price.legend(fontsize=8, loc="upper left")
        ax_price.grid(alpha=0.3)

        if "volume" in df.columns:
            ax_vol.bar(df.index, df["volume"], color="#383835", width=(df.index[1] - df.index[0]) * 0.8)
        ax_vol.set_ylabel("Volumen")
        ax_vol.set_xlabel("Fecha")
        ax_vol.grid(alpha=0.2)
        fig.autofmt_xdate(rotation=30, ha="right")
        fig.tight_layout()
    return fig


def strategy_comparison_chart(dates, series: dict[str, np.ndarray], symbol_label: str) -> plt.Figure:
    """Comparacion de retorno acumulado (%) de varias series de equity/precio
    normalizadas al mismo punto de partida, una linea por serie."""
    with plt.style.context("dark_background"):
        fig, ax = plt.subplots(figsize=(12, 5.5))
        palette = ["#3d7dff", "#898781", "#33d17a", "#d95926", "#c98500", "#d55181"]
        for (label, values), color in zip(series.items(), palette):
            ax.plot(dates, values, linewidth=1.6 if label != "Buy & Hold" else 1.2, color=color, label=label)
        ax.axhline(0, color="#898781", linewidth=0.8, linestyle=":")
        ax.set_title(f"{symbol_label} — Comparacion de Retorno Acumulado", fontsize=13, fontweight="bold")
        ax.set_ylabel("Retorno acumulado (%)")
        ax.set_xlabel("Fecha")
        ax.legend(fontsize=8, loc="upper left")
        ax.grid(alpha=0.3)
        fig.autofmt_xdate(rotation=30, ha="right")
        fig.tight_layout()
    return fig
