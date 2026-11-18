import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import plotly.graph_objects as go
import streamlit as st

from core import config
from core.daily_levels import calculate_daily_levels
from core.data import fetch_ohlcv
from core.state import render_refresh_control
from ui.theme import inject_css

inject_css()
st.title("Niveles diarios M5 · XAU/USD")
st.caption(
    "Gráfico de referencia para el día siguiente: H07, H1130 y L16 se calculan "
    "con velas M5 cerradas y permanecen congelados durante el día activo."
)

with st.sidebar:
    st.header("Configuración")
    period = st.selectbox("Histórico", ["30d", "60d"], index=0)
    third_hour = st.number_input("Hora del tercer nivel", min_value=0, max_value=23, value=16)
    third_minute = st.number_input("Minuto del tercer nivel", min_value=0, max_value=59, value=0, step=5)
    third_mode_label = st.selectbox(
        "Ancla del tercer nivel",
        ["Vela que cierra a esa hora", "Vela que abre a esa hora"],
    )
    require_retest = st.checkbox("Exigir retesteo", value=True)
    retest_limit = st.number_input("Velas máximas para retesteo", min_value=1, max_value=100, value=12)

refresh_seconds = render_refresh_control()
df = fetch_ohlcv(period, "5m", symbol=config.SYMBOL)
if df.empty:
    st.error("No se pudieron descargar velas M5 cerradas para el símbolo configurado.")
    st.stop()

result = calculate_daily_levels(
    df,
    third_hour=int(third_hour),
    third_minute=int(third_minute),
    third_mode="open" if "abre" in third_mode_label else "close",
    require_retest=require_retest,
    retest_bars_limit=int(retest_limit),
)

if result.warning:
    st.warning(result.warning)
st.info("Zona horaria aplicada: America/El_Salvador (America/NYCK no es un identificador IANA válido).")

levels = result.active_levels
if levels:
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Conjunto activo", result.active_date or "—")
    c2.metric("H07", f"{levels['H07']:,.2f}")
    c3.metric("H1130", f"{levels['H1130']:,.2f}")
    c4.metric("L16", f"{levels['L16']:,.2f}")
else:
    st.warning("Todavía no existe un conjunto completo válido para activar.")

chart = go.Figure(
    go.Candlestick(
        x=result.data.index,
        open=result.data["open"],
        high=result.data["high"],
        low=result.data["low"],
        close=result.data["close"],
        name="XAU/USD M5",
    )
)
for column, label, color in (
    ("line_h07", "H07", "#2196F3"),
    ("line_h1130", "H1130", "#2196F3"),
    ("line_l16", "L16", "#2196F3"),
):
    chart.add_trace(
        go.Scatter(
            x=result.data.index,
            y=result.data[column],
            mode="lines",
            name=label,
            line={"color": color, "width": 2},
            connectgaps=False,
        )
    )

signals = result.data
chart.add_trace(
    go.Scatter(
        x=signals.index[signals["bull_signal"]],
        y=signals.loc[signals["bull_signal"], "close"],
        mode="markers",
        name="Señal alcista",
        marker={"color": "#00C853", "size": 11, "symbol": "triangle-up"},
    )
)
chart.add_trace(
    go.Scatter(
        x=signals.index[signals["bear_signal"]],
        y=signals.loc[signals["bear_signal"], "close"],
        mode="markers",
        name="Señal bajista",
        marker={"color": "#FF5252", "size": 11, "symbol": "triangle-down"},
    )
)
chart.update_layout(
    template="plotly_dark",
    height=720,
    xaxis_rangeslider_visible=False,
    xaxis_title="Hora local",
    yaxis_title="Precio",
    legend={"orientation": "h"},
)
st.plotly_chart(chart, width="stretch")

bias_color = {"ALCISTA": "green", "BAJISTA": "red", "NEUTRAL": "orange"}.get(result.bias, "gray")
st.subheader(f"Sesgo actual: :{bias_color}[{result.bias}]")
st.caption(
    "Las señales son informativas; esta página no abre operaciones ni envía órdenes automáticamente."
)
