"""Tarjetas de indicador con "Lo que el dashboard oculta": un numero grande +
un mini-grafico + una nota critica sobre la limitacion estadistica de ese numero
(igual patron que un dashboard de analista: la metrica de portada, y debajo el
matiz que la metrica sola no muestra)."""
from __future__ import annotations

import base64
import io

import matplotlib.pyplot as plt
import streamlit as st

from .theme import COLORS


def _fig_to_base64(fig: plt.Figure) -> str:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=130, transparent=True, bbox_inches="tight")
    plt.close(fig)
    return base64.b64encode(buf.getvalue()).decode("ascii")


def mini_bar_chart(labels: list[str], values: list[float], colors: list[str], value_fmt: str = "{:.0f}%") -> plt.Figure:
    """Barra pequeña sin ejes/titulo, pensada para vivir dentro de una tarjeta."""
    fig, ax = plt.subplots(figsize=(3.0, 1.5))
    bars = ax.bar(labels, values, color=colors, width=0.6)
    for bar, value in zip(bars, values):
        ax.text(
            bar.get_x() + bar.get_width() / 2, bar.get_height(), value_fmt.format(value),
            ha="center", va="bottom", fontsize=8, color=COLORS["text_secondary"],
        )
    ax.set_ylim(0, max(values) * 1.35 if max(values) > 0 else 1)
    ax.tick_params(axis="x", colors=COLORS["text_muted"], labelsize=8)
    ax.tick_params(axis="y", left=False, labelleft=False)
    for spine in ("top", "right", "left"):
        ax.spines[spine].set_visible(False)
    ax.spines["bottom"].set_color(COLORS["axis"])
    fig.tight_layout(pad=0.3)
    return fig


def render_insight_card(
    icon: str,
    label: str,
    value: str,
    subtitle: str,
    accent: str,
    hidden_html: str,
    fig: plt.Figure | None = None,
) -> None:
    """Tarjeta: icono + label + numero grande (borde de color `accent`), subtitulo,
    y caja ambar "Lo que el dashboard oculta" con texto + mini-grafico opcional."""
    chart_html = ""
    if fig is not None:
        b64 = _fig_to_base64(fig)
        chart_html = f'<img src="data:image/png;base64,{b64}" style="width:100%; margin-top:6px;" />'

    st.markdown(
        f"""
        <div style="
            background-color: {COLORS['bg_surface']};
            border: 1px solid rgba(255,255,255,0.08);
            border-left: 3px solid {accent};
            border-radius: 12px;
            padding: 16px 18px;
            height: 100%;
        ">
            <div style="display:flex; justify-content:space-between; align-items:flex-start;">
                <span style="color:{COLORS['text_muted']}; font-size:0.78rem; letter-spacing:0.03em; text-transform:uppercase;">{label}</span>
                <span style="font-size:1.1rem;">{icon}</span>
            </div>
            <div style="color:{COLORS['text_primary']}; font-size:2.1rem; font-weight:700; line-height:1.25; margin-top:2px;">{value}</div>
            <div style="color:{COLORS['text_muted']}; font-size:0.8rem; margin-bottom:10px;">{subtitle}</div>
            <div style="
                background: rgba(250,178,25,0.08);
                border-left: 3px solid {COLORS['warning']};
                border-radius: 8px;
                padding: 10px 12px;
            ">
                <div style="color:{COLORS['warning']}; font-size:0.72rem; font-weight:700; letter-spacing:0.03em; text-transform:uppercase; margin-bottom:4px;">
                    ⚠ Lo que la tarjeta oculta
                </div>
                <div style="color:{COLORS['text_secondary']}; font-size:0.82rem; line-height:1.4;">{hidden_html}</div>
                {chart_html}
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
