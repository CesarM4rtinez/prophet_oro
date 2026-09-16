import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import streamlit as st

from core import config
from ui.theme import inject_css

st.set_page_config(page_title=config.APP_TITLE, page_icon=config.APP_ICON, layout="wide")


def home_page() -> None:
    inject_css()
    st.title(f"{config.APP_ICON} {config.APP_TITLE}")
    st.caption(
        "Sistema de trading intradia sobre Capital.com: filtro de zonas RSI(14) (compra < 40, venta > 60) "
        "que habilita la operacion solo cuando, en esa misma condicion, la WMA(14) quiebra de direccion. "
        "Estrategia inspirada en el enfoque de Pablo Gil (seguimiento de tendencia + filtro de rango)."
    )

    st.markdown("### Secciones")
    c1, c2 = st.columns(2)
    with c1:
        st.markdown(
            '<div class="eth-card"><b>💹 Terminal</b><br><span style="opacity:0.75;">Conexion a Capital.com '
            "(DEMO/LIVE, seleccion de cuenta), Indices/Forex/Cripto/Futuros, grafico en vivo con WMA+RSI+señales, "
            "motor semi-automatico y ticket manual.</span></div>",
            unsafe_allow_html=True,
        )
    with c2:
        st.markdown(
            '<div class="eth-card"><b>🧪 Backtest</b><br><span style="opacity:0.75;">Backtest real (capital, '
            "comisiones, position sizing) de la misma maquina de estados que usa el motor en vivo, sobre "
            "velas historicas reales de Capital.com.</span></div>",
            unsafe_allow_html=True,
        )

    st.markdown("---")
    st.markdown("##### ⚠️ Advertencia de riesgo")
    st.caption(
        "Este sistema puede conectarse a una cuenta REAL de Capital.com y enviar ordenes con dinero real. "
        "Por defecto arranca en DEMO y el motor semi-automatico nunca queda armado entre reinicios. Verifica "
        "siempre los resultados del backtest y las reglas antes de armar el motor en una cuenta LIVE."
    )


pages = {
    "Dashboard": [st.Page(home_page, title="Resumen", icon="🏠", default=True)],
    "Trading": [st.Page("pages/1_terminal.py", title="Terminal", icon="💹")],
    "Validacion": [st.Page("pages/2_backtest.py", title="Backtest", icon="🧪")],
}

st.navigation(pages).run()
