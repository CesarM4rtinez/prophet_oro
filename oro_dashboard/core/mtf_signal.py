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
Institucional (SMC)" (1d/1h/5m, con retest+AMD).

Distingue dos posiciones:
- `preview`: la mejor posicion LARGA/CORTA proyectable con los datos actuales —
  requiere solo que 15m tenga tendencia definida y que exista ALGUN quiebre
  historico en 5m a favor de esa tendencia (no exige que sea el ultimo ni que
  sea reciente). Pensada para dibujarse siempre que se pueda en el grafico
  (regla 3/4 de "smoke test" visual, no de trading).
- `signal`: subconjunto de `preview` que ademas cumple las 4 reglas completas
  (BOS de continuacion en 15m + quiebre reciente y alineado en 5m) — la unica
  que se considera una señal operable de verdad."""
from __future__ import annotations

import pandas as pd

from . import config
from .smc_zones import atr
from .structure_naive import nearest_liquidity_target, own_trend


def _build_position(
    kind: str, entry_price: float, trigger: dict, swings_dir: pd.DataFrame, df_entry: pd.DataFrame
) -> dict | None:
    direction = "BUY" if kind == "alcista" else "SELL"
    tp = nearest_liquidity_target(swings_dir, kind, entry_price)
    atr_entry = float(atr(df_entry).iloc[-1])
    buffer = config.ICT_MANIPULATION_SL_ATR_MULT * atr_entry
    sl = trigger["level"] - buffer if kind == "alcista" else trigger["level"] + buffer

    valid_tp = tp is not None and ((direction == "BUY" and tp > entry_price) or (direction == "SELL" and tp < entry_price))
    valid_sl = (direction == "BUY" and sl < entry_price) or (direction == "SELL" and sl > entry_price)
    if not (valid_tp and valid_sl):
        return None

    risk = abs(entry_price - sl)
    reward = abs(tp - entry_price)
    if risk <= 0:
        return None

    return {"direction": direction, "entry": entry_price, "sl": sl, "tp": tp, "rr": reward / risk, "trigger": trigger}


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
    if direction_confirmed and entry_aligned:
        signal = _build_position(trend_dir, current_price, last_break_entry, swings_dir, df_entry)

    # Vista previa: a diferencia de la señal (que exige el ULTIMO quiebre y
    # reciente), busca hacia atras el quiebre valido mas reciente dentro de una
    # ventana mas amplia — un quiebre viejo puede quedar geometricamente
    # invalido si el precio ya se alejo de ese nivel (SL/TP del lado incorrecto
    # del precio actual), asi que se prueba con el siguiente mas reciente en
    # vez de rendirse en el primero.
    preview = signal
    if preview is None and trend_dir is not None:
        min_idx = len(df_entry) - 1 - config.BI_PREVIEW_LOOKBACK_BARS
        for brk in reversed(breaks_entry):
            if brk["idx"] < min_idx:
                break
            if brk["kind"] != trend_dir:
                continue
            candidate = _build_position(trend_dir, current_price, brk, swings_dir, df_entry)
            if candidate is not None:
                preview = candidate
                break

    return {
        "trend_dir": trend_dir,
        "trend_entry": trend_entry,
        "direction_confirmed": direction_confirmed,
        "last_break_dir": last_break_dir,
        "last_break_entry": last_break_entry,
        "entry_recent": entry_recent,
        "entry_aligned": entry_aligned,
        "current_price": current_price,
        "preview": preview,
        "signal": signal,
        "swings_dir": swings_dir,
        "swings_entry": swings_entry,
        "breaks_dir": breaks_dir,
        "breaks_entry": breaks_entry,
    }
