import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import streamlit as st

from core import config
from core.backtest import run_backtest
from core.capital_client import get_client
from ui.charts import equity_curve_chart, strategy_chart
from ui.theme import inject_css

inject_css()

st.title("🧪 Backtest — WMA(14) + Filtro RSI(14)")
st.caption(
    "Backtest real (capital, comisiones, position sizing por riesgo) usando la MISMA maquina de estados "
    "que el motor en vivo (`core/strategy.py`) — no es una segunda implementacion de las reglas."
)

creds = config.get_capital_credentials()
if not config.capital_credentials_present():
    st.error("Faltan credenciales en capital_wma_rsi_trader/.env.")
    st.stop()

if not st.session_state.get("capital_connected"):
    st.info("👈 Conecta tu cuenta desde la pagina Terminal primero (misma sesion del navegador).")
    st.stop()

environment = st.session_state.get("capital_environment", "DEMO")
client = get_client(environment, creds.api_key, creds.identifier, creds.password)
if not client.is_connected:
    st.warning("La sesion se perdio. Vuelve a la pagina Terminal y pulsa Conectar.")
    st.stop()

c1, c2, c3 = st.columns(3)
asset_class = c1.selectbox("Clase de activo", options=list(config.CAPITAL_ASSET_CLASSES.keys()), key="bt_asset_class")
epic_input = c2.text_input("Epic o termino de busqueda (ej. EURUSD, BTCUSD, GOLD)", value=st.session_state.get("capital_selected_epic", ""))
resolution = c3.selectbox(
    "Temporalidad", options=config.CAPITAL_RESOLUTIONS,
    index=config.CAPITAL_RESOLUTIONS.index(config.SUGGESTED_RESOLUTION_BY_CLASS.get(asset_class, config.DEFAULT_CAPITAL_RESOLUTION)),
)

c4, c5, c6 = st.columns(3)
max_points = c4.number_input("Numero de velas", min_value=100, max_value=1000, value=500, step=50)
initial_cash = c5.number_input("Capital inicial", min_value=100.0, value=10_000.0, step=100.0)
risk_pct = c6.number_input("Riesgo por operacion (%)", min_value=0.1, max_value=10.0, value=config.RISK_PCT_DEFAULT, step=0.1)

run_clicked = st.button("▶️ Correr backtest", width="stretch", type="primary")

if run_clicked:
    if not epic_input:
        st.error("Escribe un epic o termino de busqueda.")
    else:
        try:
            with st.spinner("Buscando instrumento y trayendo velas..."):
                matches = client.search_markets(epic_input, asset_class=asset_class, limit=5)
                epic = next((m["epic"] for m in matches if m.get("epic", "").upper() == epic_input.upper()), None)
                epic = epic or (matches[0]["epic"] if matches else epic_input.upper())
                df = client.get_candles(epic, resolution=resolution, max_points=int(max_points))
            if df.empty or len(df) < config.WMA_PERIOD + 5:
                st.warning(f"No hay suficientes velas para {epic} en {resolution}.")
            else:
                with st.spinner("Corriendo backtest..."):
                    result = run_backtest(df, initial_cash=initial_cash, commission_pct=0.1, risk_pct=risk_pct)
                st.session_state["bt_result"] = result
                st.session_state["bt_epic"] = epic
                st.session_state["bt_resolution"] = resolution
        except Exception as exc:
            st.error(f"Error corriendo el backtest: {exc}")

if "bt_result" in st.session_state:
    result = st.session_state["bt_result"]
    stats = result["stats"]
    epic = st.session_state["bt_epic"]
    resolution = st.session_state["bt_resolution"]

    st.markdown(f"##### Resultados — {epic} ({resolution})")
    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Retorno", f"{stats['Return [%]']:.2f}%")
    m2.metric("# Operaciones", int(stats["# Trades"]))
    m3.metric("Win Rate", f"{stats['Win Rate [%]']:.1f}%" if pd.notna(stats["Win Rate [%]"]) else "N/D")
    m4.metric("Max. Drawdown", f"{stats['Max. Drawdown [%]']:.2f}%")
    m5.metric("Sharpe Ratio", f"{stats['Sharpe Ratio']:.2f}" if pd.notna(stats["Sharpe Ratio"]) else "N/D")

    fig = strategy_chart(result["signals"].tail(300), title=f"{epic} ({resolution})", buy_level=config.RSI_BUY_LEVEL, sell_level=config.RSI_SELL_LEVEL)
    st.plotly_chart(fig, width="stretch")

    st.plotly_chart(equity_curve_chart(result["equity_curve"]), width="stretch")

    trades = result["trades"]
    st.markdown(f"##### 📋 Operaciones ({len(trades)})")
    if trades.empty:
        st.caption("No se ejecuto ninguna operacion en este periodo (filtro RSI + WMA no coincidieron, o la muestra es corta).")
    else:
        display_trades = trades[["Size", "EntryTime", "EntryPrice", "ExitTime", "ExitPrice", "PnL", "ReturnPct"]].copy()
        display_trades["ReturnPct"] = (display_trades["ReturnPct"] * 100).round(2)
        st.dataframe(display_trades, width="stretch", hide_index=True)

    st.caption(
        "Backtest con `backtesting.lib.FractionalBacktest` (tamaños fraccionarios, como opera Capital.com via "
        "CFDs) y comision de 0.1% por operacion. No garantiza resultados futuros — verifica siempre en DEMO "
        "antes de armar el motor en una cuenta LIVE."
    )
