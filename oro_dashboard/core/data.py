"""Descarga de velas OHLCV via yfinance, con normalizacion de columnas y cache corto."""
from __future__ import annotations

import pandas as pd
import streamlit as st
import yfinance as yf

from . import config


def _flatten_columns(data: pd.DataFrame) -> pd.DataFrame:
    if isinstance(data.columns, pd.MultiIndex):
        data = data.copy()
        data.columns = data.columns.get_level_values(0)
    return data


@st.cache_data(ttl=60, show_spinner=False)
def fetch_ohlcv(period: str, interval: str, symbol: str = config.SYMBOL) -> pd.DataFrame:
    """DataFrame con columnas open/high/low/close/volume indexado por fecha (UTC)."""
    raw = yf.download(symbol, period=period, interval=interval, progress=False, auto_adjust=True)
    if raw is None or raw.empty:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])

    raw = _flatten_columns(raw)
    df = pd.DataFrame(
        {
            "open": raw["Open"].astype(float),
            "high": raw["High"].astype(float),
            "low": raw["Low"].astype(float),
            "close": raw["Close"].astype(float),
            "volume": raw["Volume"].astype(float) if "Volume" in raw.columns else 0.0,
        }
    )
    df.index = pd.to_datetime(df.index)
    df.index.name = "time"
    return df.dropna()


def fetch_interval(label: str, symbol: str = config.SYMBOL) -> pd.DataFrame:
    """Atajo para pedir uno de los intervalos predefinidos en `core.config.INTERVALS`."""
    spec = config.INTERVALS[label]
    return fetch_ohlcv(spec["period"], spec["interval"], symbol=symbol)


# Periodo yfinance mas amplio por intervalo, apuntando a una muestra ~5000 velas
# (limitado por lo que yfinance realmente permite por temporalidad) — para el
# motor SMC, que compara la zona activa contra analogos historicos.
_DEEP_PERIOD = {"5m": "60d", "15m": "60d", "1h": "730d", "1d": "max"}


def fetch_deep(label: str, symbol: str = config.SYMBOL) -> pd.DataFrame:
    spec = config.INTERVALS[label]
    period = _DEEP_PERIOD.get(label, spec["period"])
    return fetch_ohlcv(period, spec["interval"], symbol=symbol)
