"""Tema visual compartido: paleta validada (misma paleta ya validada con el skill
dataviz en el proyecto eth_dashboard), plantilla Plotly oscura y CSS."""
from __future__ import annotations

import plotly.graph_objects as go
import plotly.io as pio
import streamlit as st

COLORS = {
    "bg_page": "#0e1117",
    "bg_surface": "#161b22",
    "text_primary": "#ffffff",
    "text_secondary": "#c3c2b7",
    "text_muted": "#898781",
    "grid": "#2c2c2a",
    "axis": "#383835",
    # Estado (direccion / resultado) - reservado, nunca se reutiliza como identidad de serie.
    "bull": "#0ca30c",      # velas alcistas, LONG
    "bear": "#d03b3b",      # velas bajistas, SHORT, stop loss
    "warning": "#fab219",
    "serious": "#ec835a",
    # Series (identidad) - slots categoricos en orden fijo.
    "series_hist": "#3987e5",      # slot 1 blue - precio historico
    "series_forecast": "#199e70",  # slot 3 aqua - WMA
    "series_pattern": "#d95926",   # slot 2 orange - RSI
    "series_secondary": "#c98500",  # slot 4 yellow - niveles 40/60
    "series_marker": "#d55181",     # slot 5 magenta - marca de actualizacion
}

TEMPLATE_NAME = "wma_rsi_dark"


def get_plotly_template() -> str:
    """Registra (una sola vez) la plantilla Plotly oscura y devuelve su nombre."""
    if TEMPLATE_NAME not in pio.templates:
        pio.templates[TEMPLATE_NAME] = go.layout.Template(
            layout=go.Layout(
                paper_bgcolor=COLORS["bg_surface"],
                plot_bgcolor=COLORS["bg_surface"],
                font=dict(color=COLORS["text_secondary"], family="system-ui, -apple-system, Segoe UI, sans-serif"),
                title=dict(font=dict(color=COLORS["text_primary"], size=16), x=0.5, xanchor="center", y=0.95, yanchor="top"),
                xaxis=dict(
                    gridcolor=COLORS["grid"], linecolor=COLORS["axis"], zerolinecolor=COLORS["axis"],
                    tickfont=dict(color=COLORS["text_muted"]), rangeslider=dict(visible=False),
                ),
                yaxis=dict(gridcolor=COLORS["grid"], linecolor=COLORS["axis"], zerolinecolor=COLORS["axis"], tickfont=dict(color=COLORS["text_muted"])),
                legend=dict(bgcolor="rgba(0,0,0,0)", font=dict(color=COLORS["text_secondary"]), orientation="h", yanchor="top", y=-0.15, xanchor="center", x=0.5),
                colorway=[COLORS["series_hist"], COLORS["series_forecast"], COLORS["series_pattern"], COLORS["series_secondary"], COLORS["series_marker"]],
                margin=dict(l=10, r=40, t=60, b=40),
                hoverlabel=dict(bgcolor=COLORS["bg_page"], font=dict(color=COLORS["text_primary"])),
            )
        )
    return TEMPLATE_NAME


def inject_css() -> None:
    st.markdown(
        f"""
        <style>
        .stApp {{ background-color: {COLORS["bg_page"]}; }}
        h1, h2, h3 {{ letter-spacing: -0.01em; }}
        div[data-testid="stMetric"] {{
            background-color: {COLORS["bg_surface"]};
            border: 1px solid rgba(255,255,255,0.08);
            border-radius: 10px;
            padding: 14px 16px;
        }}
        div[data-testid="stMetricLabel"] {{ color: {COLORS["text_muted"]}; }}
        .eth-badge {{
            display: inline-block;
            padding: 3px 10px;
            border-radius: 999px;
            font-size: 0.78rem;
            font-weight: 600;
            letter-spacing: 0.02em;
        }}
        .eth-badge-demo {{ background: rgba(250,178,25,0.15); color: {COLORS["warning"]}; border: 1px solid rgba(250,178,25,0.35); }}
        .eth-badge-live {{ background: rgba(208,59,59,0.15); color: {COLORS["bear"]}; border: 1px solid rgba(208,59,59,0.4); }}
        .eth-badge-buy {{ background: rgba(12,163,12,0.15); color: {COLORS["bull"]}; border: 1px solid rgba(12,163,12,0.4); }}
        .eth-badge-sell {{ background: rgba(208,59,59,0.15); color: {COLORS["bear"]}; border: 1px solid rgba(208,59,59,0.4); }}
        .eth-badge-neutral {{ background: rgba(137,135,129,0.15); color: {COLORS["text_muted"]}; border: 1px solid rgba(137,135,129,0.35); }}
        .eth-card {{
            background-color: {COLORS["bg_surface"]};
            border: 1px solid rgba(255,255,255,0.08);
            border-radius: 12px;
            padding: 16px 18px;
            margin-bottom: 10px;
        }}
        </style>
        """,
        unsafe_allow_html=True,
    )
