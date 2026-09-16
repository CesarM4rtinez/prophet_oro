"""Indicadores base de la estrategia: WMA (Media Movil Ponderada) y RSI."""
from __future__ import annotations

import numpy as np
import pandas as pd


def wma(close: pd.Series, period: int = 14) -> pd.Series:
    """Media Movil Ponderada: los pesos crecen linealmente (1..period), el mayor
    peso lo tiene el precio mas reciente de la ventana."""
    weights = np.arange(1, period + 1, dtype=float)
    return close.rolling(period).apply(lambda w: np.dot(w, weights) / weights.sum(), raw=True)


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """RSI de Wilder (suavizado exponencial `ewm(alpha=1/period)`) -- misma formula
    ya usada y verificada en el proyecto eth_dashboard (`core/scalping.py::_rsi`)."""
    delta = close.diff()
    gain, loss = delta.clip(lower=0), -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).fillna(50.0)


def wma_direction(wma_series: pd.Series) -> pd.Series:
    """Direccion de la WMA en cada vela: 1 (ascendente), -1 (descendente), 0 (sin
    dato/plana). Comparacion contra la vela inmediatamente anterior."""
    diff = wma_series.diff()
    direction = pd.Series(0, index=wma_series.index, dtype=int)
    direction[diff > 0] = 1
    direction[diff < 0] = -1
    return direction


def wma_flip(direction: pd.Series) -> pd.Series:
    """True en la vela donde la direccion de la WMA cambia respecto a la anterior
    direccion NO-NULA registrada (quiebro: minimo o maximo local de la WMA).
    Ignora velas con direccion 0 (plana) para no perder el quiebro por un tramo
    plano intermedio."""
    flips = pd.Series(False, index=direction.index)
    last_dir = 0
    for idx, d in direction.items():
        if d == 0:
            continue
        if last_dir != 0 and d != last_dir:
            flips[idx] = True
        last_dir = d
    return flips
