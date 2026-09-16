"""Deteccion de patrones armonicos clasicos (Gartley, Bat, Butterfly, Crab) sobre
5 puntos de swing (X-A-B-C-D), usando las razones de Fibonacci publicas y bien
documentadas de cada patron. No replica ningun indicador o producto comercial
especifico — es la misma metodologia publica que cualquier scanner de patrones
armonicos usa como base.
"""
from __future__ import annotations

import pandas as pd

from .smc_zones import atr, detect_swings

# Rangos de tolerancia publicos por patron. BC/AB (0.35-0.90) es comun a los 4 y
# no discrimina por si solo — el discriminador principal es AB/XA y, sobre todo,
# XD/XA (donde termina D en proporcion al tramo XA).
PATTERN_RATIOS: dict[str, dict[str, tuple[float, float]]] = {
    "Gartley": {"ab_xa": (0.58, 0.66), "bc_ab": (0.35, 0.90), "xd_xa": (0.75, 0.82)},
    "Bat": {"ab_xa": (0.35, 0.52), "bc_ab": (0.35, 0.90), "xd_xa": (0.84, 0.92)},
    "Butterfly": {"ab_xa": (0.74, 0.82), "bc_ab": (0.35, 0.90), "xd_xa": (1.20, 1.65)},
    "Crab": {"ab_xa": (0.35, 0.66), "bc_ab": (0.35, 0.90), "xd_xa": (1.55, 1.70)},
}


def swing_points(df: pd.DataFrame, lookback: int = 5) -> list[dict]:
    """Swings alternados (high/low) ordenados por tiempo. Si aparecen dos swings
    consecutivos del mismo tipo, se conserva el mas extremo (evita "dobles picos"
    triviales que romperian la alternancia High-Low-High-Low esperada)."""
    swings = detect_swings(df, lookback=lookback)
    points: list[dict] = []
    for i in range(len(df)):
        if swings["swing_high"].iloc[i]:
            points.append({"idx": i, "price": float(df["high"].iloc[i]), "kind": "high"})
        if swings["swing_low"].iloc[i]:
            points.append({"idx": i, "price": float(df["low"].iloc[i]), "kind": "low"})
    points.sort(key=lambda p: p["idx"])

    collapsed: list[dict] = []
    for p in points:
        if collapsed and collapsed[-1]["kind"] == p["kind"]:
            more_extreme = (p["price"] > collapsed[-1]["price"]) if p["kind"] == "high" else (p["price"] < collapsed[-1]["price"])
            if more_extreme:
                collapsed[-1] = p
            continue
        collapsed.append(p)
    return collapsed


def _classify(ab_xa: float, bc_ab: float, xd_ratio: float) -> str | None:
    for name, ratios in PATTERN_RATIOS.items():
        lo1, hi1 = ratios["ab_xa"]
        lo2, hi2 = ratios["bc_ab"]
        lo3, hi3 = ratios["xd_xa"]
        if lo1 <= ab_xa <= hi1 and lo2 <= bc_ab <= hi2 and lo3 <= xd_ratio <= hi3:
            return name
    return None


def detect_harmonic_patterns(df: pd.DataFrame, lookback: int = 5, max_patterns: int = 5) -> dict:
    """Devuelve {"completed": [...], "forming": [...]}.

    "completed": patrones con los 5 puntos X-A-B-C-D confirmados y clasificados
    (Gartley/Bat/Butterfly/Crab), con entry=D, sl (ATR en la vela de D), tp1/tp2
    (retrocesos 38.2%/61.8% del tramo A-D) y rr.

    "forming": X-A-B-C confirmados sin D todavia; se proyecta la Zona Potencial de
    Reversion (PRZ) para cada patron cuyas razones AB/XA y BC/AB ya calzan.
    """
    points = swing_points(df, lookback=lookback)
    atr_series = atr(df)
    completed: list[dict] = []
    forming: list[dict] = []

    for i in range(len(points) - 3):
        x, a, b, c = points[i], points[i + 1], points[i + 2], points[i + 3]
        kinds = (x["kind"], a["kind"], b["kind"], c["kind"])
        if kinds not in (("low", "high", "low", "high"), ("high", "low", "high", "low")):
            continue

        bias = "alcista" if x["kind"] == "low" else "bajista"
        xa_range = a["price"] - x["price"]  # con signo: positivo si alcista, negativo si bajista
        ab_range = b["price"] - a["price"]
        bc_range = c["price"] - b["price"]
        xa, ab, bc = abs(xa_range), abs(ab_range), abs(bc_range)
        if xa <= 0 or ab <= 0 or bc <= 0:
            continue
        ab_xa, bc_ab = ab / xa, bc / ab

        d = points[i + 4] if i + 4 < len(points) else None
        if d is not None and d["kind"] == x["kind"]:
            # xd_ratio: retroceso de D medido desde A sobre el tramo XA, con signo
            # (funciona igual para alcista/bajista sin ramas separadas).
            xd_ratio = (a["price"] - d["price"]) / xa_range
            name = _classify(ab_xa, bc_ab, xd_ratio)
            if name is None:
                continue
            entry = d["price"]
            sign = 1 if bias == "alcista" else -1
            ad = abs(a["price"] - entry)
            tp1 = entry + sign * 0.382 * ad
            tp2 = entry + sign * 0.618 * ad
            atr_value = float(atr_series.iloc[d["idx"]]) or entry * 0.005
            sl = entry - sign * atr_value * 0.5
            risk = abs(entry - sl)
            rr = abs(tp2 - entry) / risk if risk > 0 else None
            completed.append(
                {
                    "name": name,
                    "bias": bias,
                    "status": "completado",
                    "points": {"X": x, "A": a, "B": b, "C": c, "D": d},
                    "entry": entry,
                    "sl": sl,
                    "tp1": tp1,
                    "tp2": tp2,
                    "rr": rr,
                }
            )
        elif d is None:
            for name, ratios in PATTERN_RATIOS.items():
                lo1, hi1 = ratios["ab_xa"]
                lo2, hi2 = ratios["bc_ab"]
                if not (lo1 <= ab_xa <= hi1 and lo2 <= bc_ab <= hi2):
                    continue
                lo3, hi3 = ratios["xd_xa"]
                d_lo = a["price"] - lo3 * xa_range
                d_hi = a["price"] - hi3 * xa_range
                forming.append(
                    {
                        "name": name,
                        "bias": bias,
                        "status": "en formacion",
                        "points": {"X": x, "A": a, "B": b, "C": c},
                        "prz_top": max(d_lo, d_hi),
                        "prz_bottom": min(d_lo, d_hi),
                    }
                )

    return {"completed": completed[-max_patterns:], "forming": forming[-max_patterns:]}
