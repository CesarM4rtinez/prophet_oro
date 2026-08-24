"""Zonas SMC: swings, Break of Structure (BOS), Order Blocks y backtest de continuacion/fallo.

Incluye ademas la estrategia institucional (ICT/Smart Money Concepts) multi-timeframe:
estructura HH/HL/LL/LH + Market Structure Shift, Fair Value Gaps, barridas de liquidez,
retrocesos Fibonacci institucionales y sintesis de entradas de alta probabilidad.

Porteado de eth_dashboard/core/smc_zones.py (motor ya en uso con ETH) — no reescrito
desde cero, porque ya resuelve el problema concreto de este dashboard: una ruptura de
estructura NO se cuenta como "continuo" (señal operable) solo por cerrar mas alla de un
swing; se exige que el precio retestee la zona despues de la ruptura (`_classify_zone`)
y que haya una barrida de liquidez (patron AMD) confirmada cerca de la ruptura
(`_zone_manipulation`) antes de listar un setup. Un spike aislado que revierte de
inmediato (barrida de stops) queda `sin_confirmar`, nunca como señal alcista/bajista
limpia — a diferencia del motor anterior (`core/structure_mtf.py`, eliminado), que
confirmaba tendencia con el primer cierre mas alla del ultimo swing.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import streamlit as st

from . import config
from .data import fetch_deep


def detect_swings(df: pd.DataFrame, lookback: int = 5) -> pd.DataFrame:
    """Marca swing highs/lows confirmados (requieren `lookback` velas a cada lado)."""
    high, low = df["high"].to_numpy(), df["low"].to_numpy()
    n = len(df)
    swing_high = np.zeros(n, dtype=bool)
    swing_low = np.zeros(n, dtype=bool)
    for i in range(lookback, n - lookback):
        window_high = high[i - lookback : i + lookback + 1]
        window_low = low[i - lookback : i + lookback + 1]
        if high[i] == window_high.max():
            swing_high[i] = True
        if low[i] == window_low.min():
            swing_low[i] = True
    out = df.copy()
    out["swing_high"] = swing_high
    out["swing_low"] = swing_low
    return out


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high, low, close = df["high"], df["low"], df["close"]
    prev_close = close.shift(1)
    tr = pd.concat([high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
    return tr.rolling(period, min_periods=1).mean()


def _last_opposite_candle(open_, close, from_idx: int, to_idx: int, bullish_break: bool):
    """Ultima vela bajista (si ruptura alcista) o alcista (si ruptura bajista) antes de la ruptura."""
    for j in range(to_idx - 1, from_idx - 1, -1):
        is_bearish_candle = close[j] < open_[j]
        is_bullish_candle = close[j] > open_[j]
        if bullish_break and is_bearish_candle:
            return j
        if not bullish_break and is_bullish_candle:
            return j
    return None


def _nearest_above(level: float, points: list[tuple[int, float]]) -> float | None:
    above = [v for _, v in points if v > level]
    return float(min(above)) if above else None


def _nearest_below(level: float, points: list[tuple[int, float]]) -> float | None:
    below = [v for _, v in points if v < level]
    return float(max(below)) if below else None


def detect_order_blocks(df: pd.DataFrame, lookback: int = 5, sl_atr_mult: float = 0.5, max_zones: int = 8) -> list[dict]:
    """Detecta rupturas de estructura (BOS) y el Order Block que las origino.

    El take-profit apunta a la liquidez mas cercana en la direccion del movimiento:
    el swing high mas cercano por ENCIMA del order block para zonas alcistas, o el
    swing low mas cercano por DEBAJO para zonas bajistas (nunca del lado del stop).
    """
    swings = detect_swings(df, lookback=lookback)
    atr_series = atr(df)
    open_, close = df["open"].to_numpy(), df["close"].to_numpy()
    high, low = df["high"].to_numpy(), df["low"].to_numpy()
    n = len(df)

    all_swing_highs = [(i, high[i]) for i in range(n) if swings["swing_high"].iloc[i]]
    all_swing_lows = [(i, low[i]) for i in range(n) if swings["swing_low"].iloc[i]]

    last_sh_idx = last_sh_val = None
    last_sl_idx = last_sl_val = None
    broken_highs, broken_lows = set(), set()
    zones: list[dict] = []

    for i in range(n):
        if swings["swing_high"].iloc[i]:
            last_sh_idx, last_sh_val = i, high[i]
        if swings["swing_low"].iloc[i]:
            last_sl_idx, last_sl_val = i, low[i]

        if last_sh_idx is not None and i > last_sh_idx and last_sh_idx not in broken_highs and close[i] > last_sh_val:
            broken_highs.add(last_sh_idx)
            ob_idx = _last_opposite_candle(open_, close, last_sh_idx, i, bullish_break=True)
            if ob_idx is not None:
                top, bottom = max(open_[ob_idx], close[ob_idx]), min(open_[ob_idx], close[ob_idx])
                zones.append(
                    {
                        "kind": "bullish",
                        "ob_idx": ob_idx,
                        "break_idx": i,
                        "start_idx": ob_idx,
                        "end_idx": min(i + 40, n - 1),
                        "top": float(top),
                        "bottom": float(bottom),
                        "broken_level": float(last_sh_val),
                        "sl": float(bottom - sl_atr_mult * atr_series.iloc[ob_idx]),
                        "tp": _nearest_above(top, all_swing_highs),
                    }
                )

        if last_sl_idx is not None and i > last_sl_idx and last_sl_idx not in broken_lows and close[i] < last_sl_val:
            broken_lows.add(last_sl_idx)
            ob_idx = _last_opposite_candle(open_, close, last_sl_idx, i, bullish_break=False)
            if ob_idx is not None:
                top, bottom = max(open_[ob_idx], close[ob_idx]), min(open_[ob_idx], close[ob_idx])
                zones.append(
                    {
                        "kind": "bearish",
                        "ob_idx": ob_idx,
                        "break_idx": i,
                        "start_idx": ob_idx,
                        "end_idx": min(i + 40, n - 1),
                        "top": float(top),
                        "bottom": float(bottom),
                        "broken_level": float(last_sl_val),
                        "sl": float(top + sl_atr_mult * atr_series.iloc[ob_idx]),
                        "tp": _nearest_below(bottom, all_swing_lows),
                    }
                )

    for zone in zones:
        status, retested = _classify_zone(df, zone)
        zone["status"] = status
        zone["retested"] = retested

    return zones[-max_zones:]


def _classify_zone(df: pd.DataFrame, zone: dict) -> tuple[str, bool]:
    """Tras la ruptura: ¿el precio retesta la zona y luego alcanza el target, o la invalida primero?
    Devuelve (status, retested) — retested indica si el precio volvio a tocar la zona
    antes de resolverse, independientemente del resultado final."""
    high, low, close = df["high"].to_numpy(), df["low"].to_numpy(), df["close"].to_numpy()
    n = len(df)
    start, end = zone["break_idx"] + 1, min(zone["end_idx"], n - 1)
    if zone["tp"] is None or start >= end:
        return "sin_datos", False

    retested = False
    for j in range(start, end + 1):
        if low[j] <= zone["top"] and high[j] >= zone["bottom"]:
            retested = True
        if retested:
            if zone["kind"] == "bullish":
                if close[j] <= zone["sl"]:
                    return "fallo", retested
                if close[j] >= zone["tp"]:
                    return "continuo", retested
            else:
                if close[j] >= zone["sl"]:
                    return "fallo", retested
                if close[j] <= zone["tp"]:
                    return "continuo", retested
    return "sin_confirmar", retested


def zone_stats(zones: list[dict]) -> dict:
    total = len(zones)
    if total == 0:
        return {"total": 0, "continuo_pct": 0.0, "fallo_pct": 0.0}
    continuo = sum(1 for z in zones if z["status"] == "continuo")
    fallo = sum(1 for z in zones if z["status"] == "fallo")
    return {"total": total, "continuo_pct": continuo / total * 100, "fallo_pct": fallo / total * 100}


# --- Estrategia institucional (ICT/SMC) ----------------------------------------


def label_structure(df: pd.DataFrame, lookback: int = 5) -> dict:
    """Clasifica los swings confirmados como HH/HL/LL/LH (comparando cada swing contra
    el swing anterior del mismo tipo), determina el sesgo vigente por mayoria de los
    ultimos swings, y localiza el ultimo Market Structure Shift (MSS): un cierre que
    rompe en contra del sesgo vigente."""
    swings = detect_swings(df, lookback=lookback)
    high, low, close = df["high"].to_numpy(), df["low"].to_numpy(), df["close"].to_numpy()
    n = len(df)

    labeled: list[dict] = []
    prev_high = prev_low = None
    for i in range(n):
        if swings["swing_high"].iloc[i]:
            if prev_high is not None:
                label = "HH" if high[i] > prev_high else "LH"
                labeled.append({"idx": i, "label": label, "price": float(high[i])})
            prev_high = high[i]
        if swings["swing_low"].iloc[i]:
            if prev_low is not None:
                label = "HL" if low[i] > prev_low else "LL"
                labeled.append({"idx": i, "label": label, "price": float(low[i])})
            prev_low = low[i]
    labeled.sort(key=lambda s: s["idx"])

    recent = labeled[-4:]
    bullish_votes = sum(1 for s in recent if s["label"] in ("HH", "HL"))
    bearish_votes = sum(1 for s in recent if s["label"] in ("LL", "LH"))
    if bullish_votes > bearish_votes:
        bias = "alcista"
    elif bearish_votes > bullish_votes:
        bias = "bajista"
    else:
        bias = "indefinido"

    mss = None
    last_sh_idx = last_sh_val = last_sl_idx = last_sl_val = None
    for i in range(n):
        if swings["swing_high"].iloc[i]:
            last_sh_idx, last_sh_val = i, high[i]
        if swings["swing_low"].iloc[i]:
            last_sl_idx, last_sl_val = i, low[i]
        if bias == "alcista" and last_sl_idx is not None and i > last_sl_idx and close[i] < last_sl_val:
            mss = {"idx": i, "kind": "bajista", "level": float(last_sl_val)}
        elif bias == "bajista" and last_sh_idx is not None and i > last_sh_idx and close[i] > last_sh_val:
            mss = {"idx": i, "kind": "alcista", "level": float(last_sh_val)}

    return {"bias": bias, "swings": labeled, "mss": mss}


def detect_fair_value_gaps(df: pd.DataFrame, max_zones: int = 20) -> list[dict]:
    """Fair Value Gaps (imbalances) de 3 velas: hueco entre high[i-1] y low[i+1]
    (alcista) o entre low[i-1] y high[i+1] (bajista), sin solaparse con la vela
    intermedia (la de "desplazamiento")."""
    high, low = df["high"].to_numpy(), df["low"].to_numpy()
    n = len(df)
    gaps = []
    for i in range(1, n - 1):
        if low[i + 1] > high[i - 1]:
            gaps.append({"kind": "bullish", "idx": i, "top": float(low[i + 1]), "bottom": float(high[i - 1])})
        elif high[i + 1] < low[i - 1]:
            gaps.append({"kind": "bearish", "idx": i, "top": float(low[i - 1]), "bottom": float(high[i + 1])})

    for gap in gaps:
        gap["status"] = _classify_fvg_fill(df, gap)
    return gaps[-max_zones:]


def _classify_fvg_fill(df: pd.DataFrame, gap: dict) -> str:
    high, low = df["high"].to_numpy(), df["low"].to_numpy()
    for j in range(gap["idx"] + 2, len(df)):
        if low[j] <= gap["top"] and high[j] >= gap["bottom"]:
            return "mitigado"
    return "sin_mitigar"


def detect_liquidity_sweeps(df: pd.DataFrame, lookback: int = 5, max_sweeps: int = 20) -> list[dict]:
    """Barrida de liquidez: la mecha de una vela supera el swing MAS RECIENTE (no
    cualquier swing antiguo), pero el cierre queda del lado contrario (trampa de
    stops antes del movimiento real). Cada swing solo puede generar una barrida."""
    swings = detect_swings(df, lookback=lookback)
    high, low, close = df["high"].to_numpy(), df["low"].to_numpy(), df["close"].to_numpy()
    n = len(df)

    sweeps = []
    last_sh_idx = last_sh_val = None
    last_sl_idx = last_sl_val = None
    swept_highs: set[int] = set()
    swept_lows: set[int] = set()

    for i in range(n):
        if (
            last_sh_idx is not None
            and last_sh_idx not in swept_highs
            and high[i] > last_sh_val
            and close[i] < last_sh_val
        ):
            sweeps.append({"kind": "bearish", "idx": i, "level": float(last_sh_val)})
            swept_highs.add(last_sh_idx)
        if (
            last_sl_idx is not None
            and last_sl_idx not in swept_lows
            and low[i] < last_sl_val
            and close[i] > last_sl_val
        ):
            sweeps.append({"kind": "bullish", "idx": i, "level": float(last_sl_val)})
            swept_lows.add(last_sl_idx)

        if swings["swing_high"].iloc[i]:
            last_sh_idx, last_sh_val = i, high[i]
        if swings["swing_low"].iloc[i]:
            last_sl_idx, last_sl_val = i, low[i]

    return sweeps[-max_sweeps:]


def institutional_fibonacci(df: pd.DataFrame, lookback: int = 5) -> dict | None:
    """Retrocesos institucionales (61.8/70.5/79%) del ultimo swing significativo:
    zona de descuento (para comprar) si el sesgo es alcista, o premium (para vender)
    si es bajista."""
    swings = detect_swings(df, lookback=lookback)
    highs = [(i, float(df["high"].iloc[i])) for i in range(len(df)) if swings["swing_high"].iloc[i]]
    lows = [(i, float(df["low"].iloc[i])) for i in range(len(df)) if swings["swing_low"].iloc[i]]
    if not highs or not lows:
        return None

    last_high_idx, last_high = highs[-1]
    last_low_idx, last_low = lows[-1]
    span = last_high - last_low
    if span <= 0:
        return None

    bias = "alcista" if last_high_idx > last_low_idx else "bajista"
    pcts = {"50%": 0.5, "61.8%": 0.618, "70.5%": 0.705, "79%": 0.79}

    if bias == "alcista":
        levels = {label: last_high - span * pct for label, pct in pcts.items()}
    else:
        levels = {label: last_low + span * pct for label, pct in pcts.items()}

    zone_values = list(levels.values())
    return {
        "bias": bias,
        "range_top": last_high,
        "range_bottom": last_low,
        "equilibrium": (last_high + last_low) / 2,
        "levels": {k: float(v) for k, v in levels.items()},
        "zone_top": float(max(zone_values)),
        "zone_bottom": float(min(zone_values)),
    }


def _zone_manipulation(
    zone: dict,
    df_structure: pd.DataFrame,
    structure_sweeps: list[dict],
    entry_sweeps: list[dict],
    df_entry: pd.DataFrame,
    max_lag: pd.Timedelta = pd.Timedelta(hours=6),
) -> dict | None:
    """Busca la barrida de liquidez (patron AMD: Acumulacion-Manipulacion-Distribucion)
    que precede/acompaña la ruptura de una zona, en estructura o en entrada. Sin
    barrida no hay "manipulacion" confirmada y la zona se descarta."""
    expected_kind = "bullish" if zone["kind"] == "bullish" else "bearish"
    zone_time = df_structure.index[zone["break_idx"]]

    candidates: list[tuple[pd.Timestamp, dict]] = []
    for s in structure_sweeps:
        if s["kind"] == expected_kind:
            candidates.append((df_structure.index[s["idx"]], s))
    for s in entry_sweeps:
        if s["kind"] == expected_kind:
            candidates.append((df_entry.index[s["idx"]], s))

    candidates = [(t, s) for t, s in candidates if t <= zone_time + max_lag]
    if not candidates:
        return None
    candidates.sort(key=lambda pair: pair[0])
    return candidates[-1][1]


def _manipulation_stop(
    sweep: dict,
    df_entry: pd.DataFrame,
    buffer_atr_mult: float = config.ICT_MANIPULATION_SL_ATR_MULT,
    at_idx: int | None = None,
) -> float:
    """Stop de precision: nivel barrido +/- un colchon pequeño (proporcional al ATR de
    la entrada, para no depender de "pips"/% fijos que no aplican igual en distintas
    volatilidades). `at_idx` permite fijar el ATR en un punto historico especifico
    (backtest); por defecto usa la ultima vela (uso en vivo)."""
    atr_series = atr(df_entry)
    idx = at_idx if at_idx is not None else len(df_entry) - 1
    entry_atr = float(atr_series.iloc[idx])
    buffer = buffer_atr_mult * entry_atr
    if sweep["kind"] == "bullish":
        return sweep["level"] - buffer
    return sweep["level"] + buffer


def _find_retest_idx(df: pd.DataFrame, zone: dict) -> int | None:
    """Primer indice, despues de la ruptura, en que el precio vuelve a tocar la
    zona (retest) — el punto real de entrada, no la barra de la ruptura misma
    (que ya quedo fuera de la zona por definicion)."""
    high, low = df["high"].to_numpy(), df["low"].to_numpy()
    n = len(df)
    start, end = zone["break_idx"] + 1, min(zone["end_idx"], n - 1)
    for j in range(start, end + 1):
        if low[j] <= zone["top"] and high[j] >= zone["bottom"]:
            return j
    return None


def historical_qualified_setups(df: pd.DataFrame, lookback: int = 5, min_rr: float = config.ICT_MIN_RR) -> list[dict]:
    """Version de un solo timeframe de la calificacion AMD + RR minimo que usa
    `multi_timeframe_bias`, pero sobre TODAS las zonas historicas resueltas (no solo
    las mas recientes) — pensada para alimentar un backtest, no la vista en vivo.

    La entrada se dispara en el RETEST de la zona (regla de oro: "esperar a que el
    precio testee la zona"), no en la barra de ruptura — ahi el precio ya quedo
    fuera de la zona por definicion.
    """
    zones = detect_order_blocks(df, lookback=lookback, max_zones=len(df))
    sweeps = detect_liquidity_sweeps(df, lookback=lookback, max_sweeps=len(df))

    setups = []
    for zone in zones:
        if zone["status"] not in ("continuo", "fallo") or zone["tp"] is None:
            continue
        sweep = _zone_manipulation(zone, df, sweeps, sweeps, df)
        if sweep is None:
            continue
        retest_idx = _find_retest_idx(df, zone)
        if retest_idx is None:
            continue
        # Precio real en la barra de retest (no el borde teorico de la zona) — es el
        # mismo precio que usara el backtest para decidir la entrada, asi que el
        # RR se calcula contra ese precio para que quede internamente consistente.
        entry_price = float(df["close"].iloc[retest_idx])
        sl = _manipulation_stop(sweep, df, at_idx=sweep["idx"])
        risk = abs(entry_price - sl)
        if risk <= 0:
            continue
        rr = abs(zone["tp"] - entry_price) / risk
        if rr < min_rr:
            continue

        direction = "BUY" if zone["kind"] == "bullish" else "SELL"
        valid_bracket = (sl < entry_price < zone["tp"]) if direction == "BUY" else (zone["tp"] < entry_price < sl)
        if not valid_bracket:
            continue

        setups.append({"entry_idx": retest_idx, "direction": direction, "sl": sl, "tp": zone["tp"]})
    return setups


def multi_timeframe_bias(
    df_bias: pd.DataFrame,
    df_structure: pd.DataFrame,
    df_entry: pd.DataFrame,
    lookback: int = 5,
    min_rr: float = config.ICT_MIN_RR,
) -> dict:
    """Sintetiza la estrategia institucional multi-timeframe: sesgo macro (df_bias),
    order blocks + barridas de liquidez de la estructura (df_structure), y contexto
    de entrada -FVG + Fibonacci- (df_entry) en una lista de entradas de alta
    probabilidad.

    Un setup solo se incluye si cumple las reglas de oro: (1) order block confirmado
    (`continuo`) alineado con el sesgo macro, (2) patron AMD -manipulacion de liquidez
    confirmada cerca de la ruptura, sin ella no hay entrada-, y (3) Riesgo/Beneficio
    minimo `min_rr` usando el stop de precision (nivel manipulado +/- colchon ATR)."""
    bias_info = label_structure(df_bias, lookback=lookback)
    macro_bias = bias_info["bias"]

    structure_zones = detect_order_blocks(df_structure, lookback=lookback)
    structure_sweeps = detect_liquidity_sweeps(df_structure, lookback=lookback)

    entry_fvgs = detect_fair_value_gaps(df_entry)
    entry_sweeps = detect_liquidity_sweeps(df_entry, lookback=lookback)
    entry_fib = institutional_fibonacci(df_entry, lookback=lookback)

    if macro_bias in ("alcista", "bajista"):
        aligned_zones = [
            z for z in structure_zones
            if z["status"] == "continuo" and ((z["kind"] == "bullish") == (macro_bias == "alcista"))
        ]
    else:
        aligned_zones = []

    current_price = float(df_entry["close"].iloc[-1])

    setups = []
    for zone in aligned_zones[-5:]:
        sweep = _zone_manipulation(zone, df_structure, structure_sweeps, entry_sweeps, df_entry)
        if sweep is None:
            continue  # sin patron AMD (manipulacion) confirmado: la regla de oro dice no operar

        direction = "BUY" if zone["kind"] == "bullish" else "SELL"
        sl = _manipulation_stop(sweep, df_entry)
        tp = zone["tp"]
        if tp is None:
            continue
        risk = abs(current_price - sl)
        reward = abs(tp - current_price)
        if risk <= 0:
            continue
        rr = reward / risk
        if rr < min_rr:
            continue

        setups.append(
            {
                "direccion": direction,
                "motivo": (
                    f"Order block {zone['kind']} alineado con sesgo {macro_bias} ({config.ICT_STRUCTURE_INTERVAL}), "
                    f"continuo, con barrida de liquidez confirmada (AMD) — RR {rr:.1f}"
                ),
                "zona_top": zone["top"],
                "zona_bottom": zone["bottom"],
                "sl": sl,
                "tp": tp,
                "rr": rr,
                "amd_confirmado": True,
            }
        )

    return {
        "macro_bias": macro_bias,
        "macro_mss": bias_info["mss"],
        "current_price": current_price,
        "structure_zones": structure_zones,
        "structure_sweeps": structure_sweeps,
        "entry_fvgs": entry_fvgs,
        "entry_sweeps": entry_sweeps,
        "entry_fib": entry_fib,
        "high_probability_setups": setups,
    }


# --- Motor de probabilidad estadistica (aproximacion tipo "Order Block Scanner") ----


def zone_probability(
    zones: list[dict],
    current_zone: dict,
    atr_value: float,
    recent_n: int = config.PROBABILITY_RECENT_STRUCTURE_N,
    tolerance: float = config.PROBABILITY_ANALOG_TOLERANCE,
) -> dict | None:
    """Aproxima la probabilidad de continuacion de `current_zone` comparandola con
    analogos historicos (mismo tipo, altura de zona similar en proporcion al ATR) y
    con el desempeño reciente de los ultimos `recent_n` quiebres de estructura del
    mismo tipo. No replica ningun algoritmo propietario: es una aproximacion
    estadistica generica."""
    if atr_value <= 0:
        return None
    current_height = current_zone["top"] - current_zone["bottom"]
    if current_height <= 0:
        return None
    current_ratio = current_height / atr_value

    resolved = [z for z in zones if z["status"] in ("continuo", "fallo")]
    analogs = [
        z for z in resolved
        if z is not current_zone
        and z["kind"] == current_zone["kind"]
        and abs(((z["top"] - z["bottom"]) / atr_value) - current_ratio) <= tolerance * current_ratio
    ]
    if not analogs:
        return None

    analog_continuation = sum(1 for z in analogs if z["status"] == "continuo") / len(analogs) * 100
    analog_retest = sum(1 for z in analogs if z.get("retested")) / len(analogs) * 100

    same_direction_recent = [z for z in resolved if z["kind"] == current_zone["kind"]][-recent_n:]
    recent_success = (
        sum(1 for z in same_direction_recent if z["status"] == "continuo") / len(same_direction_recent) * 100
        if same_direction_recent
        else analog_continuation
    )

    probability = (analog_continuation + recent_success) / 2

    if probability >= 70:
        tier, fires = "Excelente", 3
    elif probability >= 60:
        tier, fires = "Buena", 2
    elif probability >= 50:
        tier, fires = "Aceptable", 1
    else:
        tier, fires = "Neutral / evitar", 0

    return {
        "probability": probability,
        "analog_continuation_pct": analog_continuation,
        "recent_structure_success_pct": recent_success,
        "retest_pct": analog_retest,
        "sample_size": len(analogs),
        "tier": tier,
        "fires": fires,
        "low_retest_warning": analog_retest < config.PROBABILITY_RETEST_WARNING_PCT,
    }


def multi_timeframe_probability(df_1h: pd.DataFrame, df_15m: pd.DataFrame, df_5m: pd.DataFrame, lookback: int = 5) -> dict:
    """Confluencia multi-timeframe (regla de oro: nunca operar en base a una sola
    temporalidad). Corre `zone_probability` sobre la zona mas reciente de 1h/15m/5m,
    exige que al menos 2 de las 3 coincidan en direccion, y promedia la probabilidad
    entre las que tienen datos: (Prob_T1 + Prob_T2 + Prob_T3) / 3."""
    per_timeframe: dict[str, dict | None] = {}
    for label, df in (("1h", df_1h), ("15m", df_15m), ("5m", df_5m)):
        if df is None or df.empty or len(df) < 60:
            per_timeframe[label] = None
            continue
        zones = detect_order_blocks(df, lookback=lookback, max_zones=200)
        if not zones:
            per_timeframe[label] = None
            continue
        current = zones[-1]
        atr_value = float(atr(df).iloc[-1])
        prob = zone_probability(zones, current, atr_value)
        per_timeframe[label] = (
            {
                "kind": current["kind"],
                "prob": prob,
                "zone": current,
                "current_price": float(df["close"].iloc[-1]),
                "atr": atr_value,
            }
            if prob
            else None
        )

    valid = [r for r in per_timeframe.values() if r and r["prob"]]
    kinds = {r["kind"] for r in valid}
    aligned = len(valid) >= 2 and len(kinds) == 1
    avg_probability = sum(r["prob"]["probability"] for r in valid) / len(valid) if valid else None

    return {
        "per_timeframe": per_timeframe,
        "aligned": aligned,
        "aligned_kind": next(iter(kinds)) if aligned else None,
        "avg_probability": avg_probability,
    }


def build_zone_signal(mtf_prob: dict) -> dict | None:
    """A partir de una `multi_timeframe_probability` ya alineada, arma una señal
    concreta de Entry/SL/TP1-5 para "la zona activa": usa la temporalidad mas
    inmediata disponible (prioriza 5m > 15m > 1h) para el precio de entrada, y el
    objetivo de liquidez opuesto ya calculado por `detect_order_blocks`
    (`zone["tp"]`) fraccionado en `config.PROBABILITY_SIGNAL_TP_FRACTIONS` niveles
    de toma de parcial — TP5 coincide exactamente con ese objetivo. El SL sale del
    borde opuesto de la zona mas un colchon de ATR.

    Nunca inventa un precio: si la zona no tiene objetivo (`tp`) o si SL/TP no
    quedan del lado correcto del entry, devuelve None."""
    if not mtf_prob["aligned"]:
        return None
    direction = "BUY" if mtf_prob["aligned_kind"] == "bullish" else "SELL"

    entry_info = None
    entry_timeframe = None
    for label in ("5m", "15m", "1h"):
        info = mtf_prob["per_timeframe"].get(label)
        if info and info["prob"] and info["kind"] == mtf_prob["aligned_kind"]:
            entry_info = info
            entry_timeframe = label
            break
    if entry_info is None:
        return None

    zone = entry_info["zone"]
    entry = entry_info["current_price"]
    tp_final = zone.get("tp")
    if tp_final is None:
        return None

    buffer = entry_info["atr"] * config.ICT_MANIPULATION_SL_ATR_MULT
    sl = zone["bottom"] - buffer if direction == "BUY" else zone["top"] + buffer

    valid_tp = (direction == "BUY" and tp_final > entry) or (direction == "SELL" and tp_final < entry)
    valid_sl = (direction == "BUY" and sl < entry) or (direction == "SELL" and sl > entry)
    if not (valid_tp and valid_sl):
        return None

    tp_distance = tp_final - entry
    tps = [entry + tp_distance * frac for frac in config.PROBABILITY_SIGNAL_TP_FRACTIONS]
    risk = abs(entry - sl)
    reward = abs(tps[-1] - entry)

    return {
        "direction": direction,
        "timeframe": entry_timeframe,
        "entry": entry,
        "sl": sl,
        "tps": tps,
        "rr": reward / risk if risk > 0 else None,
    }


@st.cache_data(ttl=120, show_spinner="Calculando probabilidad estadistica multi-timeframe...")
def cached_multi_timeframe_probability(lookback: int = 5) -> dict:
    """Version cacheada (120s) de multi_timeframe_probability — recorrer ~5000 velas
    en 3 temporalidades es pesado para repetir en cada tick de un fragment."""
    df_1h = fetch_deep("1h")
    df_15m = fetch_deep("15m")
    df_5m = fetch_deep("5m")
    return multi_timeframe_probability(df_1h, df_15m, df_5m, lookback=lookback)
