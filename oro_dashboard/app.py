import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import streamlit as st

from core import config
from core.data import fetch_interval
from core.timeutil import current_session_label, to_new_york_time
from core.state import render_refresh_control
from ui.theme import inject_css, render_data_status

st.set_page_config(page_title=config.APP_TITLE, page_icon=config.APP_ICON, layout="wide")


def home_page() -> None:
    inject_css()
    st.title(f"{config.APP_ICON} {config.APP_TITLE}")
    st.caption(
        "Analitica de oro (XAU/USD) via el proxy PAXG-USD: pronostico Prophet, patrones tecnicos, "
        "probabilidad historica de targets, plan de trading para la killzone de Nueva York y "
        "confirmacion de estructura multi-temporalidad (5m/15m/1h)."
    )

    refresh_seconds = render_refresh_control()

    @st.fragment(run_every=refresh_seconds or None)
    def render_ticker() -> None:
        df = fetch_interval("1d")
        if df.empty:
            st.warning("No se pudieron obtener datos para el simbolo configurado.")
            return
        last_ts = df.index[-1]
        render_data_status(to_new_york_time(last_ts), current_session_label(last_ts))

        last = float(df["close"].iloc[-1])
        change = (last / float(df["close"].iloc[-2]) - 1) * 100 if len(df) > 1 else 0.0
        c1, c2 = st.columns(2)
        c1.metric(f"{config.SYMBOL_LABEL} — Precio actual", f"${last:,.2f}", f"{change:+.2f}% (1d)")
        c2.metric("Fuente de datos", f"Yahoo Finance · {config.SYMBOL}")

    render_ticker()

    st.markdown("### Secciones del dashboard")
    cards = [
        ("📈 Pronostico Prophet", "Historico + prediccion a 30 dias con banda de incertidumbre del 95%, exportable a Excel."),
        ("🔍 Patrones Tecnicos", "Picos, valles, patron armonico ABCD y hombro-cabeza-hombro (15m)."),
        ("🎯 Probabilidad de Targets", "Backtest de probabilidad global, por regimen de tendencia y cruzado con el calendario economico."),
        ("🕗 Plan Killzone NY", "Entrada/SL/TP para la sesion de Nueva York, con eventos economicos del dia."),
        ("🧭 Estructura Multi-Temporalidad", "Confirmacion de BOS entre 5m/15m/1h y veredicto de señal operable."),
    ]
    cols = st.columns(3)
    for i, (card_title, desc) in enumerate(cards):
        with cols[i % 3]:
            st.markdown(
                f'<div class="oro-card"><b>{card_title}</b><br><span style="opacity:0.75;">{desc}</span></div>',
                unsafe_allow_html=True,
            )


pages = {
    "Dashboard": [st.Page(home_page, title="Resumen", icon="🏠", default=True)],
    "Analitica": [
        st.Page("pages/forecast.py", title="Pronostico Prophet", icon="📈"),
        st.Page("pages/patterns.py", title="Patrones Tecnicos", icon="🔍"),
        st.Page("pages/probability.py", title="Probabilidad de Targets", icon="🎯"),
        st.Page("pages/killzone.py", title="Plan Killzone NY", icon="🕗"),
        st.Page("pages/structure_mtf.py", title="Estructura Multi-Temporalidad", icon="🧭"),
    ],
}

st.navigation(pages).run()
