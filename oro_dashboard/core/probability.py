"""Backtests de probabilidad de alcanzar target/stoploss, global y condicional por
regimen de tendencia, para compra o para venta (celdas 5, 10, 13 y 15 del notebook)."""
from __future__ import annotations

import numpy as np
import pandas as pd


def _levels(start: float, sl_pct: float, t1_pct: float, t2_pct: float, direction: str) -> tuple[float, float, float]:
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
        sl, t1, t2 = _levels(segment[0], sl_pct, t1_pct, t2_pct, direction)
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

        sl, t1, t2 = _levels(segment[0], sl_pct, t1_pct, t2_pct, direction)
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
