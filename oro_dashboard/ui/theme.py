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
        div[data-testid="stMetricValue"], div[data-testid="stMetricValue"] * {{
            font-size: 1.5rem !important;
            line-height: 1.25 !important;
            white-space: normal !important;
            overflow: visible !important;
            text-overflow: clip !important;
            overflow-wrap: anywhere !important;
        }}
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
        .oro-kpi-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 12px; margin-bottom: 16px; }}
        .oro-rule-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(230px, 1fr)); gap: 12px; }}
        .oro-kpi-tile {{
            background-color: {COLORS["bg_surface"]};
            border: 1px solid rgba(255,255,255,0.08);
            border-radius: 12px;
            padding: 14px 16px 16px;
            position: relative;
            overflow: hidden;
            height: 100%;
        }}
        .oro-kpi-tile .accent {{ position: absolute; left: 0; top: 0; bottom: 0; width: 3px; }}
        .oro-kpi-tile .label {{
            font-size: 0.72rem; color: {COLORS["text_muted"]}; text-transform: uppercase;
            letter-spacing: 0.04em; margin-bottom: 8px;
        }}
        .oro-kpi-tile .value {{ font-size: 1.5rem; font-weight: 700; letter-spacing: -0.01em; line-height: 1.2; color: {COLORS["text_primary"]}; }}
        .oro-kpi-tile .delta {{ font-size: 0.74rem; margin-top: 6px; color: {COLORS["text_muted"]}; }}
        .oro-rule-card {{
            background-color: {COLORS["bg_surface"]};
            border: 1px solid rgba(255,255,255,0.08);
            border-left: 3px solid {COLORS["series_hist"]};
            border-radius: 10px;
            padding: 13px 16px;
            height: 100%;
        }}
        .oro-rule-card h4 {{ margin: 0 0 6px; font-size: 0.84rem; color: {COLORS["text_primary"]}; }}
        .oro-rule-card p {{ margin: 0; font-size: 0.8rem; color: {COLORS["text_secondary"]}; line-height: 1.55; }}
        .oro-rule-card.done {{ border-left-color: {COLORS["bull"]}; }}
        .oro-rule-card.pending {{ border-left-color: {COLORS["warning"]}; }}
        .oro-signal-pill {{
            display: inline-flex; align-items: center; gap: 8px; font-weight: 800;
            font-size: 1.15rem; padding: 9px 20px; border-radius: 999px; letter-spacing: 0.02em;
        }}
        .oro-signal-pill.buy {{ background: rgba(12,163,12,0.18); color: #3ddc3d; border: 1px solid rgba(12,163,12,0.5); }}
        .oro-signal-pill.sell {{ background: rgba(208,59,59,0.18); color: #ff6b6b; border: 1px solid rgba(208,59,59,0.5); }}
        .oro-signal-pill.wait {{ background: rgba(250,178,25,0.15); color: #ffce6a; border: 1px solid rgba(250,178,25,0.45); }}
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_kpi_tile(label: str, value: str, delta: str = "", accent: str = "") -> str:
    """HTML de una tarjeta KPI compacta (grid de resumen tipo BI). Devuelve el
    string para componer varias en una sola llamada a `st.markdown` (evita el
    parpadeo de N llamadas sueltas)."""
    accent = accent or COLORS["series_hist"]
    delta_html = f'<div class="delta">{delta}</div>' if delta else ""
    return (
        f'<div class="oro-kpi-tile"><div class="accent" style="background:{accent}"></div>'
        f'<div class="label">{label}</div><div class="value">{value}</div>{delta_html}</div>'
    )


def render_rule_card(number: int, title: str, text: str, status: str = "") -> str:
    """HTML de una tarjeta de regla (metodologia) con estado 'done'/'pending'/''."""
    status_class = f" {status}" if status in ("done", "pending") else ""
    return (
        f'<div class="oro-rule-card{status_class}"><h4>{number}. {title}</h4><p>{text}</p></div>'
    )


def render_signal_pill(kind: str, text: str) -> str:
    """kind: 'buy' | 'sell' | 'wait'."""
    return f'<span class="oro-signal-pill {kind}">{text}</span>'


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
