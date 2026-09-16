"""Ubicacion del minimo/maximo previo mas cercano al momento de una entrada, para
colocar el Stop Loss. Pivote simple (1 vela a cada lado) -- deliberadamente mas
rapido/reactivo que un swing SMC confirmado con velas futuras (core/smc_zones.py
del proyecto eth_dashboard), que no serviria para un SL calculado en vivo en la
misma vela de entrada.

Un pivote en el indice `j` solo se considera CONFIRMADO si hay `lookback` velas
disponibles a cada lado (`j - lookback` .. `j + lookback`) -- por eso la busqueda
nunca usa velas mas alla de `entry_idx` (causal: solo datos ya conocidos al
momento de decidir la entrada)."""
from __future__ import annotations

import pandas as pd


def nearest_prior_pivot_low(df: pd.DataFrame, entry_idx: int, lookback: int = 3) -> float | None:
    """Precio del pivote de minimo confirmado mas reciente ANTES de `entry_idx`.
    None si no hay ninguno disponible con los datos vistos hasta `entry_idx`."""
    low = df["low"].to_numpy()
    max_j = entry_idx - lookback
    if max_j < lookback:
        return None
    for j in range(max_j, lookback - 1, -1):
        window = low[j - lookback : j + lookback + 1]
        if low[j] == window.min():
            return float(low[j])
    return None


def nearest_prior_pivot_high(df: pd.DataFrame, entry_idx: int, lookback: int = 3) -> float | None:
    """Precio del pivote de maximo confirmado mas reciente ANTES de `entry_idx`."""
    high = df["high"].to_numpy()
    max_j = entry_idx - lookback
    if max_j < lookback:
        return None
    for j in range(max_j, lookback - 1, -1):
        window = high[j - lookback : j + lookback + 1]
        if high[j] == window.max():
            return float(high[j])
    return None
