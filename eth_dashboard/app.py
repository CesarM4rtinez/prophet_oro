import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import streamlit as st

from core import config
from core.data_provider import get_ohlcv
from core.smc_zones import current_session_label, to_new_york_time
from core.state import render_data_source_controls
from ui.theme import inject_css, render_data_status

st.set_page_config(page_title=config.APP_TITLE, page_icon=config.APP_ICON, layout="wide")


def home_page() -> None:
    inject_css()
    st.title(f"{config.APP_ICON} {config.APP_TITLE}")
    st.caption(
        "Dashboard de analitica en tiempo real y terminal de trading. Estrategia principal: "
        "Smart Money Concepts / ICT institucional multi-timeframe (sesgo, estructura, order blocks, "
        "liquidez, FVG y Fibonacci institucional), mas modulos complementarios de Prophet, patrones y scalping."
    )

    controls = render_data_source_controls()
    
    df = get_ohlcv(controls["source"], controls["symbol"], controls["interval"], exchange=controls["exchange"])
    if not df.empty:
        last_ts = df.index[-1]
        render_data_status(to_new_york_time(last_ts), current_session_label(last_ts))

        last = float(df["close"].iloc[-1])
        change = (last / float(df["close"].iloc[-2]) - 1) * 100 if len(df) > 1 else 0.0
        c1, c2, c3 = st.columns(3)
        c1.metric(f"{controls['symbol']} — Precio actual", f"${last:,.2f}", f"{change:+.2f}%")
        c2.metric("Fuente de datos", "Yahoo Finance" if controls["source"] == "yfinance" else f"ccxt · {controls['exchange']}")
        c3.metric("Intervalo", controls["interval"])
    else:
        st.warning("No se pudieron obtener datos para el simbolo/fuente seleccionado.")
    
    st.markdown("### Secciones del dashboard")
    cards = [
        ("🧠 Estrategia Institucional (SMC)", "Estrategia principal: sesgo multi-timeframe, order blocks, liquidez, FVG y Fibonacci institucional."),
        ("📈 Pronostico Prophet", "Historico + prediccion a 30 dias con banda de incertidumbre del 95%."),
        ("🔍 Patrones Tecnicos", "Picos, valles, patron armonico ABCD y hombro-cabeza-hombro."),
        ("🎯 Probabilidad de Targets", "Backtest historico de probabilidad de alcanzar target/stoploss."),
        ("⚡ Scalping + Monte Carlo", "Scorecard multi-indicador, confluencia multi-timeframe y fan chart GBM."),
        ("💹 Terminal de Trading", "Conexion a Capital.com: monitor en vivo, ordenes manuales y motor semi-automatico."),
    ]
    cols = st.columns(3)
    for i, (card_title, desc) in enumerate(cards):
        with cols[i % 3]:
            st.markdown(
                f'<div class="eth-card"><b>{card_title}</b><br><span style="opacity:0.75;">{desc}</span></div>',
                unsafe_allow_html=True,
            )


pages = {
    "Dashboard": [st.Page(home_page, title="Resumen", icon="🏠", default=True)],
    "Analitica": [
        st.Page("pages/smc.py", title="Estrategia Institucional (SMC)", icon="🧠"),
        st.Page("pages/forecast.py", title="Pronostico Prophet", icon="📈"),
        st.Page("pages/patterns.py", title="Patrones Tecnicos", icon="🔍"),
        st.Page("pages/probability.py", title="Probabilidad de Targets", icon="🎯"),
        st.Page("pages/scalping.py", title="Scalping + Monte Carlo", icon="⚡"),
    ],
    "Trading": [st.Page("pages/terminal.py", title="Terminal de Trading", icon="💹")],
    "Validacion": [st.Page("pages/backtest.py", title="Backtesting Real", icon="🧪")],
}

st.navigation(pages).run()
