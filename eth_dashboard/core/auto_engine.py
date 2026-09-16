"""Evaluacion de señales para el modo semi-automatico de la Terminal de Trading."""
from __future__ import annotations

import pandas as pd

from . import config
from .scalping import compute_indicators, score_last
from .smc_zones import multi_timeframe_bias

RULES = [
    "Scalping: score por encima del umbral",
    "SMC Institucional: entrada de alta probabilidad (multi-timeframe)",
]


def evaluate_rule(
    rule: str,
    candles: pd.DataFrame,
    threshold: float = 0.5,
    extra_candles: dict[str, pd.DataFrame] | None = None,
) -> tuple[bool, str, str]:
    """Devuelve (disparado, direccion BUY/SELL, motivo). No ejecuta ninguna orden.

    `candles` es siempre el timeframe de entrada de la regla activa. `extra_candles`
    (opcional) trae `{"bias": df_diario, "structure": df_estructura}` — solo lo
    necesita la regla institucional multi-timeframe.
    """
    if rule == RULES[0]:
        result = score_last(compute_indicators(candles))
        if result["score"] >= threshold:
            return True, "BUY", f"Score scalping {result['score']:+.2f} >= {threshold:+.2f}"
        if result["score"] <= -threshold:
            return True, "SELL", f"Score scalping {result['score']:+.2f} <= {-threshold:+.2f}"
        return False, "", ""

    if rule == RULES[1]:
        extra_candles = extra_candles or {}
        df_bias = extra_candles.get("bias")
        df_structure = extra_candles.get("structure")
        if df_bias is None or df_bias.empty or df_structure is None or df_structure.empty:
            return False, "", ""

        result = multi_timeframe_bias(df_bias, df_structure, candles, min_rr=config.ICT_MIN_RR)
        setups = result["high_probability_setups"]
        if setups:
            setup = setups[-1]
            return True, setup["direccion"], setup["motivo"]
        return False, "", ""

    return False, "", ""
