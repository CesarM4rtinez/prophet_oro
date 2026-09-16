"""Estado y controles globales compartidos entre las paginas de analitica."""
from __future__ import annotations

import streamlit as st

from . import config


def init_state() -> None:
    st.session_state.setdefault("data_source", "yfinance")
    st.session_state.setdefault("yfinance_symbol", config.DEFAULT_YFINANCE_SYMBOL)
    st.session_state.setdefault("ccxt_exchange", config.DEFAULT_CCXT_EXCHANGE)
    st.session_state.setdefault("ccxt_symbol", config.DEFAULT_CCXT_SYMBOL)
    st.session_state.setdefault("interval", config.DEFAULT_INTERVAL)
    st.session_state.setdefault("refresh_label", "30 s")


def render_data_source_controls() -> dict:
    """Dibuja los controles globales en la sidebar y devuelve la seleccion resuelta."""
    init_state()
    st.sidebar.markdown("### 🛰️ Fuente de datos")
    source_label = st.sidebar.radio(
        "Origen",
        options=["Yahoo Finance (yfinance)", "Exchange cripto (ccxt)"],
        index=0 if st.session_state["data_source"] == "yfinance" else 1,
        key="data_source_radio",
    )
    st.session_state["data_source"] = "yfinance" if source_label.startswith("Yahoo") else "ccxt"

    exchange = None
    if st.session_state["data_source"] == "yfinance":
        symbol = st.sidebar.selectbox(
            "Simbolo",
            options=list(config.YFINANCE_SYMBOLS.keys()),
            format_func=lambda s: f"{s} · {config.YFINANCE_SYMBOLS[s]}",
            key="yfinance_symbol",
        )
    else:
        exchange = st.sidebar.selectbox("Exchange", options=config.CCXT_EXCHANGES, key="ccxt_exchange")
        symbol = st.sidebar.selectbox(
            "Simbolo",
            options=list(config.CCXT_SYMBOLS.keys()),
            format_func=lambda s: f"{s} · {config.CCXT_SYMBOLS[s]}",
            key="ccxt_symbol",
        )

    interval = st.sidebar.selectbox(
        "Intervalo de velas",
        options=list(config.INTERVALS.keys()),
        key="interval",
    )

    refresh_label = st.sidebar.selectbox(
        "Auto-refresco",
        options=list(config.REFRESH_OPTIONS.keys()),
        key="refresh_label",
    )

    return {
        "source": st.session_state["data_source"],
        "symbol": symbol,
        "exchange": exchange,
        "interval": interval,
        "refresh_seconds": config.REFRESH_OPTIONS[refresh_label],
    }
