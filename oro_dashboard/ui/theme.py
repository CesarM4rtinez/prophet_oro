"""Tema visual: paleta oscura consistente con eth_dashboard, plantilla Plotly y CSS."""
from __future__ import annotations

from datetime import datetime

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
    "bull": "#0ca30c",
    "bear": "#d03b3b",
    "warning": "#fab219",
    "serious": "#ec835a",
    "series_hist": "#3987e5",
    "series_forecast": "#199e70",
    "series_pattern": "#d95926",
    "series_zone": "#9085e9",
    "series_secondary": "#c98500",
    "series_marker": "#d55181",
}

TEMPLATE_NAME = "oro_dark"


def get_plotly_template() -> str:
    """Registra (una sola vez) la plantilla Plotly oscura del dashboard y devuelve su nombre."""
    if TEMPLATE_NAME not in pio.templates:
        pio.templates[TEMPLATE_NAME] = go.layout.Template(
            layout=go.Layout(
                paper_bgcolor=COLORS["bg_surface"],
                plot_bgcolor=COLORS["bg_surface"],
                font=dict(color=COLORS["text_secondary"], family="system-ui, -apple-system, Segoe UI, sans-serif"),
                title=dict(font=dict(color=COLORS["text_primary"], size=16), x=0.5, xanchor="center", y=0.95, yanchor="top"),
                xaxis=dict(
                    gridcolor=COLORS["grid"],
                    linecolor=COLORS["axis"],
                    zerolinecolor=COLORS["axis"],
                    tickfont=dict(color=COLORS["text_muted"]),
                    rangeslider=dict(visible=False),
                ),
                yaxis=dict(
                    gridcolor=COLORS["grid"],
                    linecolor=COLORS["axis"],
                    zerolinecolor=COLORS["axis"],
                    tickfont=dict(color=COLORS["text_muted"]),
                ),
                legend=dict(
                    bgcolor="rgba(0,0,0,0)",
                    font=dict(color=COLORS["text_secondary"]),
                    orientation="h",
                    yanchor="top",
                    y=-0.22,
                    xanchor="center",
                    x=0.5,
                ),
                colorway=[
                    COLORS["series_hist"],
                    COLORS["series_forecast"],
                    COLORS["series_pattern"],
                    COLORS["series_zone"],
                    COLORS["series_secondary"],
                    COLORS["series_marker"],
                ],
                margin=dict(l=10, r=40, t=70, b=90),
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
        .oro-badge {{
            display: inline-block;
            padding: 3px 10px;
            border-radius: 999px;
            font-size: 0.78rem;
            font-weight: 600;
            letter-spacing: 0.02em;
        }}
        .oro-badge-active {{ background: rgba(12,163,12,0.15); color: {COLORS["bull"]}; border: 1px solid rgba(12,163,12,0.4); }}
        .oro-badge-idle {{ background: rgba(250,178,25,0.15); color: {COLORS["warning"]}; border: 1px solid rgba(250,178,25,0.35); }}
        .oro-card {{
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


def render_data_status(when: datetime, session_label: str) -> None:
    """Barra compacta con la fecha/hora (Nueva York) a la que estan actualizados los
    datos mostrados, y la sesion de mayor liquidez vigente en ese momento."""
    in_session = session_label != "Fuera de sesion"
    badge_class = "oro-badge-active" if in_session else "oro-badge-idle"
    icon = "🟢" if in_session else "⚪"
    st.markdown(
        f'<div style="margin: -4px 0 12px 0;">'
        f'<span class="oro-badge {badge_class}">{icon} Sesion: {session_label}</span>'
        f'<span style="margin-left: 10px; color: {COLORS["text_muted"]}; font-size: 0.82rem;">'
        f'🕐 Datos al {when.strftime("%d/%m %H:%M")} (NY)</span>'
        f"</div>",
        unsafe_allow_html=True,
    )
