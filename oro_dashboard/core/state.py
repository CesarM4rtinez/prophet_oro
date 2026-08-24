"""Controles globales compartidos entre paginas (aqui solo el auto-refresco: el
simbolo esta fijo en `core.config.SYMBOL`, no hace falta selector de fuente/activo)."""
from __future__ import annotations

import streamlit as st

from . import config


def render_refresh_control() -> int:
    st.sidebar.markdown(f"### 🥇 {config.SYMBOL_LABEL}")
    st.sidebar.caption(f"Datos via yfinance · simbolo `{config.SYMBOL}` (proxy spot de oro)")
    refresh_label = st.sidebar.selectbox(
        "Auto-refresco", options=list(config.REFRESH_OPTIONS.keys()),
        index=list(config.REFRESH_OPTIONS.keys()).index(config.DEFAULT_REFRESH_LABEL),
        key="refresh_label",
    )
    return config.REFRESH_OPTIONS[refresh_label]
