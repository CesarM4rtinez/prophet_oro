"""Backtests de probabilidad de alcanzar target/stoploss, global y condicional por
regimen de tendencia, para compra o para venta (celdas 5, 10, 13 y 15 del notebook)."""
from __future__ import annotations

import numpy as np
import pandas as pd


def direction_levels(start: float, sl_pct: float, t1_pct: float, t2_pct: float, direction: str) -> tuple[float, float, float]:
    """(stoploss, target1, target2) para `start` segun direccion (celdas 13/15 del notebook)."""
    if direction == "compra":
        return start * (1 - sl_pct), start * (1 + t1_pct), start * (1 + t2_pct)
    # venta: stoploss por ENCIMA de la entrada, targets por DEBAJO (celda 15, espejo de compra)
    return start * (1 + sl_pct), start * (1 - t1_pct), start * (1 - t2_pct)


def _first_hit(segment: np.ndarray, sl: float, t1: float, t2: float, direction: str) -> str | None:
    for price in segment[1:]:
        if direction == "compra":
            if price <= sl:
                return "Stoploss"
            if price >= t2:
                return "Target2"
            if price >= t1:
                return "Target1"
        else:
            if price >= sl:
                return "Stoploss"
            if price <= t2:
                return "Target2"
            if price <= t1:
                return "Target1"
    return None


def backtest_targets(
    close: np.ndarray,
    window: int = 30,
    sl_pct: float = 0.01,
    t1_pct: float = 0.01,
    t2_pct: float = 0.02,
    direction: str = "compra",
) -> dict:
    counts = {"Target1": 0, "Target2": 0, "Stoploss": 0, "Total": 0}
    for i in range(len(close) - window):
        segment = close[i : i + window]
        sl, t1, t2 = direction_levels(segment[0], sl_pct, t1_pct, t2_pct, direction)
        hit = _first_hit(segment, sl, t1, t2, direction)
        if hit:
            counts[hit] += 1
        counts["Total"] += 1

    total = counts["Total"] or 1
    return {
        "target1_pct": counts["Target1"] / total * 100,
        "target2_pct": counts["Target2"] / total * 100,
        "stoploss_pct": counts["Stoploss"] / total * 100,
        "sample_size": counts["Total"],
    }


def _first_hit_intrabar(high: np.ndarray, low: np.ndarray, sl: float, t1: float, t2: float, direction: str) -> str | None:
    """Igual que `_first_hit` pero mirando las mechas (High/Low) en vez de solo el
    cierre — un stop/target se puede tocar intravela sin que el CIERRE llegue a
    romperlo. Cuando una misma vela toca ambos lados (SL y TP), se asume el peor
    caso (Stoploss primero), porque OHLC no dice cual paso primero."""
    for h, l in zip(high[1:], low[1:]):
        if direction == "compra":
            if l <= sl:
                return "Stoploss"
            if h >= t2:
                return "Target2"
            if h >= t1:
                return "Target1"
        else:
            if h >= sl:
                return "Stoploss"
            if l <= t2:
                return "Target2"
            if l <= t1:
                return "Target1"
    return None


def backtest_targets_intrabar(
    high: np.ndarray,
    low: np.ndarray,
    close: np.ndarray,
    window: int = 30,
    sl_pct: float = 0.01,
    t1_pct: float = 0.01,
    t2_pct: float = 0.02,
    direction: str = "compra",
) -> dict:
    """Version intrabar de `backtest_targets`: la entrada de cada ventana sigue
    siendo el CIERRE (asi se coloca la orden en la practica), pero el "primer
    toque" de SL/TP se juzga contra High/Low, no solo contra el cierre — mas
    realista que `backtest_targets`, que subestima cuantas veces se toca el nivel
    porque una mecha puede tocarlo y el precio cerrar del otro lado."""
    counts = {"Target1": 0, "Target2": 0, "Stoploss": 0, "Total": 0}
    for i in range(len(close) - window):
        start = close[i]
        seg_high = high[i : i + window]
        seg_low = low[i : i + window]
        sl, t1, t2 = direction_levels(start, sl_pct, t1_pct, t2_pct, direction)
        hit = _first_hit_intrabar(seg_high, seg_low, sl, t1, t2, direction)
        if hit:
            counts[hit] += 1
        counts["Total"] += 1

    total = counts["Total"] or 1
    return {
        "target1_pct": counts["Target1"] / total * 100,
        "target2_pct": counts["Target2"] / total * 100,
        "stoploss_pct": counts["Stoploss"] / total * 100,
        "sample_size": counts["Total"],
    }


def backtest_by_trend(
    close: np.ndarray,
    window: int = 30,
    sl_pct: float = 0.01,
    t1_pct: float = 0.01,
    t2_pct: float = 0.02,
    slope_threshold: float = 0.05,
    direction: str = "compra",
) -> pd.DataFrame:
    buckets = {r: {"Target1": 0, "Target2": 0, "Stoploss": 0, "Total": 0} for r in ("Alcista", "Bajista", "Lateral")}
    for i in range(len(close) - window):
        segment = close[i : i + window]
        slope = np.polyfit(range(window), segment, 1)[0]
        regime = "Alcista" if slope > slope_threshold else "Bajista" if slope < -slope_threshold else "Lateral"

        sl, t1, t2 = direction_levels(segment[0], sl_pct, t1_pct, t2_pct, direction)
        hit = _first_hit(segment, sl, t1, t2, direction)
        if hit:
            buckets[regime][hit] += 1
        buckets[regime]["Total"] += 1

    def pct(bucket: dict, key: str) -> float:
        return bucket[key] / bucket["Total"] * 100 if bucket["Total"] > 0 else 0.0

    return pd.DataFrame(
        {
            "Regimen": list(buckets.keys()),
            "Target1 (%)": [pct(buckets[r], "Target1") for r in buckets],
            "Target2 (%)": [pct(buckets[r], "Target2") for r in buckets],
            "Stoploss (%)": [pct(buckets[r], "Stoploss") for r in buckets],
            "Muestras": [buckets[r]["Total"] for r in buckets],
        }
    )
