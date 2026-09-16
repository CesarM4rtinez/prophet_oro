"""Backtests de probabilidad de alcanzar target/stoploss, global y condicional por regimen de tendencia."""
from __future__ import annotations

import numpy as np
import pandas as pd


def _first_hit(segment: np.ndarray, sl: float, t1: float, t2: float) -> str | None:
    for price in segment[1:]:
        if price <= sl:
            return "Stoploss"
        if price >= t2:
            return "Target2"
        if price >= t1:
            return "Target1"
    return None


def backtest_targets(
    close: np.ndarray, window: int = 30, sl_pct: float = 0.01, t1_pct: float = 0.01, t2_pct: float = 0.02
) -> dict:
    counts = {"Target1": 0, "Target2": 0, "Stoploss": 0, "Total": 0}
    for i in range(len(close) - window):
        segment = close[i : i + window]
        start = segment[0]
        hit = _first_hit(segment, start * (1 - sl_pct), start * (1 + t1_pct), start * (1 + t2_pct))
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
) -> pd.DataFrame:
    buckets = {
        r: {"Target1": 0, "Target2": 0, "Stoploss": 0, "Total": 0} for r in ("Alcista", "Bajista", "Lateral")
    }
    for i in range(len(close) - window):
        segment = close[i : i + window]
        start = segment[0]
        slope = np.polyfit(range(window), segment, 1)[0]
        regime = "Alcista" if slope > slope_threshold else "Bajista" if slope < -slope_threshold else "Lateral"

        hit = _first_hit(segment, start * (1 - sl_pct), start * (1 + t1_pct), start * (1 + t2_pct))
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
