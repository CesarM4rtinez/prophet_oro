"""Selector unificado de fuente de datos de mercado: yfinance o ccxt."""
from __future__ import annotations

import pandas as pd

from . import config
from .data_ccxt import fetch_ohlcv as _fetch_ccxt
from .data_yfinance import fetch_ohlcv as _fetch_yfinance


def _resample_ohlcv(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    """Reagrupa velas OHLCV a una temporalidad mayor (ej. 60m -> 4h) para fuentes
    que no ofrecen ese intervalo nativo."""
    if df.empty:
        return df
    out = df.resample(rule).agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"})
    return out.dropna()


def get_ohlcv(source: str, symbol: str, interval: str, exchange: str | None = None) -> pd.DataFrame:
    """Devuelve OHLCV normalizado (open/high/low/close/volume) para la fuente seleccionada."""
    spec = config.INTERVALS[interval]
    if source == "yfinance":
        df = _fetch_yfinance(symbol, spec["yfinance_period"], spec["yfinance"])
        resample_rule = spec.get("resample_from")
        return _resample_ohlcv(df, resample_rule) if resample_rule else df
    if source == "ccxt":
        return _fetch_ccxt(exchange or config.DEFAULT_CCXT_EXCHANGE, symbol, spec["ccxt"], spec["ccxt_limit"])
    raise ValueError(f"Fuente de datos desconocida: {source}")


# Periodo yfinance mas amplio por intervalo, apuntando a una muestra ~5000 velas
# (limitado por lo que yfinance realmente permite por temporalidad).
_DEEP_YFINANCE_PERIOD = {"5m": "60d", "15m": "60d", "1h": "730d", "1d": "max"}
_DEEP_CCXT_LIMIT = 5000


def get_ohlcv_deep(source: str, symbol: str, interval: str, exchange: str | None = None) -> pd.DataFrame:
    """Historial profundo (apunta a ~5000 velas) para calculos estadisticos que
    necesitan una muestra grande (motor de probabilidad), separado de las ventanas
    mas livianas que usan los graficos normales."""
    spec = config.INTERVALS[interval]
    if source == "yfinance":
        period = _DEEP_YFINANCE_PERIOD.get(interval, spec["yfinance_period"])
        return _fetch_yfinance(symbol, period, spec["yfinance"])
    if source == "ccxt":
        return _fetch_ccxt(exchange or config.DEFAULT_CCXT_EXCHANGE, symbol, spec["ccxt"], _DEEP_CCXT_LIMIT)
    raise ValueError(f"Fuente de datos desconocida: {source}")
