"""Graficos matplotlib que replican EXACTAMENTE el estilo de proyecciones_oro.ipynb
(celdas 13/15 - Probabilidad Condicional de Targets por Patron, compra/venta) y de
proyecciones_oro_estructura.ipynb (Estructura Multi-Temporalidad 5m/15m/1h).

Se usan a proposito graficos matplotlib (no Plotly como el resto de `ui/charts.py`):
el usuario quiere ver en el dashboard la misma identidad visual que ya conoce de esas
celdas del notebook, no una reinterpretacion con otra libreria."""
from __future__ import annotations

from datetime import datetime

import matplotlib.pyplot as plt
import pandas as pd

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
) -> plt.Figure:
    """3 paneles apilados (uno por temporalidad), cada uno con su tendencia vigente,
    swings marcados y sus propias lineas de Entrada/SL/TP.

    `panels`: [{"label": "1h"/"15m"/"5m", "df": DataFrame con columnas close/high/low/
    swing_high/swing_low, "kind": "bullish"/"bearish"/None, "entry": float|None,
    "sl": float|None, "tp": float|None}]
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

            if panel.get("entry") is not None:
                ax.axhline(panel["entry"], color="blue", linestyle="--", linewidth=1.2,
                           label=f"Entrada: {panel['entry']:,.2f}")
            if panel.get("sl") is not None:
                ax.axhline(panel["sl"], color="red", linestyle="--", linewidth=1.2,
                           label=f"SL: {panel['sl']:,.2f}")
            if panel.get("tp") is not None:
                ax.axhline(panel["tp"], color="lime", linestyle="--", linewidth=1.2,
                           label=f"TP: {panel['tp']:,.2f}")

            ax.set_title(
                f"{panel['label']} — tendencia vigente: {trend_label}",
                color=color_trend, fontsize=12, fontweight="bold",
            )
            ax.legend(fontsize=7, loc="upper left", ncol=2)
            ax.grid(alpha=0.3)
            _format_x_axis(ax, df_tf.index)

        titulo_veredicto = "SIN CONFIRMACION — no operar" if veredicto is None else f"SENAL {veredicto.upper()}"
        fig.suptitle(
            f"{symbol_label} — Estructura Multi-Temporalidad (5m / 15m / 1h) — {titulo_veredicto}",
            fontsize=15, fontweight="bold",
        )
        fig.tight_layout()
    return fig
