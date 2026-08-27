"""Señal MTF de 2 temporalidades: direccion en 15m, entrada en 5m — regla pedida
explicitamente por el usuario (mas simple y directa que la cascada de 3
temporalidades de `core.smc_zones.multi_timeframe_bias`):

1. Direccion: 15m.
2. Entrada: 5m.
3. En la temporalidad de entrada (5m): buscar un QUIEBRE de estructura (BOS o
   CHoCH, cualquiera de los dos) alineado con la direccion de 15m — ese quiebre
   es el disparador de entrada.
4. En la temporalidad de direccion (15m): buscar una CONTINUACION de estructura
   (BOS, no un CHoCH recien ocurrido) — la direccion solo se da por confirmada
   si el ultimo quiebre en 15m confirma la tendencia vigente, no si la acaba de
   cambiar.

Usa el motor `core.structure_naive.own_trend` (no el motor maduro con retest+AMD
de `core.smc_zones`) a proposito: la regla pedida es dos temporalidades sin
exigir retest ni barrida de liquidez confirmada, distinta de la "Estrategia
Institucional (SMC)" (1d/1h/5m, con retest+AMD)."""
from __future__ import annotations

import pandas as pd

from . import config
from .smc_zones import atr
from .structure_naive import nearest_liquidity_target, own_trend


def mtf_15m_5m_signal(df_direction: pd.DataFrame, df_entry: pd.DataFrame, lookback: int = 5) -> dict:
    """`df_direction` = velas de 15m, `df_entry` = velas de 5m."""
    swings_dir, trend_dir, breaks_dir = own_trend(df_direction, lookback=lookback)
    swings_entry, trend_entry, breaks_entry = own_trend(df_entry, lookback=lookback)

    last_break_dir = breaks_dir[-1] if breaks_dir else None
    direction_confirmed = last_break_dir is not None and last_break_dir["tipo"] == "BOS"

    last_break_entry = breaks_entry[-1] if breaks_entry else None
    entry_recent = (
        last_break_entry is not None
        and last_break_entry["idx"] >= len(df_entry) - 1 - config.BI_ENTRY_RECENT_BARS
    )
    entry_aligned = entry_recent and trend_dir is not None and last_break_entry["kind"] == trend_dir

    current_price = float(df_entry["close"].iloc[-1])

    signal = None
    if trend_dir is not None and direction_confirmed and entry_aligned:
        direction = "BUY" if trend_dir == "alcista" else "SELL"
        entry_price = current_price
        tp = nearest_liquidity_target(swings_dir, trend_dir, entry_price)
        atr_entry = float(atr(df_entry).iloc[-1])
        buffer = config.ICT_MANIPULATION_SL_ATR_MULT * atr_entry
        sl = (
            last_break_entry["level"] - buffer if trend_dir == "alcista"
            else last_break_entry["level"] + buffer
        )
        valid_tp = tp is not None and (
            (direction == "BUY" and tp > entry_price) or (direction == "SELL" and tp < entry_price)
        )
        valid_sl = (direction == "BUY" and sl < entry_price) or (direction == "SELL" and sl > entry_price)
        if valid_tp and valid_sl:
            risk = abs(entry_price - sl)
            reward = abs(tp - entry_price)
            if risk > 0:
                signal = {
                    "direction": direction,
                    "entry": entry_price,
                    "sl": sl,
                    "tp": tp,
                    "rr": reward / risk,
                    "trigger": last_break_entry,
                }

    return {
        "trend_dir": trend_dir,
        "trend_entry": trend_entry,
        "direction_confirmed": direction_confirmed,
        "last_break_dir": last_break_dir,
        "last_break_entry": last_break_entry,
        "entry_recent": entry_recent,
        "entry_aligned": entry_aligned,
        "current_price": current_price,
        "signal": signal,
        "swings_dir": swings_dir,
        "swings_entry": swings_entry,
        "breaks_dir": breaks_dir,
        "breaks_entry": breaks_entry,
    }
