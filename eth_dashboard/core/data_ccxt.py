"""Descarga de datos OHLCV via ccxt (endpoints publicos de exchanges, sin API keys)."""
from __future__ import annotations

import ccxt
import pandas as pd
import streamlit as st


@st.cache_resource(ttl=3600, show_spinner=False)
def _get_exchange(exchange_id: str):
    exchange_class = getattr(ccxt, exchange_id)
    exchange = exchange_class({"enableRateLimit": True})
    exchange.load_markets()
    return exchange


@st.cache_data(ttl=30, show_spinner=False)
def fetch_ohlcv(exchange_id: str, symbol: str, timeframe: str, limit: int = 500) -> pd.DataFrame:
    """DataFrame con columnas open/high/low/close/volume indexado por fecha (UTC)."""
    exchange = _get_exchange(exchange_id)
    if symbol not in exchange.markets:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])

    raw = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
    if not raw:
        return pd.DataFrame(columns=["open", "high", "low", "close", "volume"])

    df = pd.DataFrame(raw, columns=["timestamp", "open", "high", "low", "close", "volume"])
    df["time"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
    df = df.set_index("time").drop(columns=["timestamp"])
    return df.astype(float)
