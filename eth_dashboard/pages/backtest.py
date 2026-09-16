import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import streamlit as st

from core import config
from core.backtest_engine import STRATEGIES, run_backtest
from core.data_provider import get_ohlcv_deep
from core.state import render_data_source_controls
from ui.charts import equity_curve_chart
from ui.theme import inject_css

inject_css()

st.title("🧪 Backtesting Real (Backtesting.py + quantstats)")
st.caption(
    "A diferencia de las estadisticas ad-hoc del resto del dashboard, esto simula capital, comisiones y "
    "tamaño de posicion real barra a barra, produciendo una curva de equity y metricas de riesgo/retorno "
    "genuinas. Resultados historicos — sin garantia de resultados futuros. Prueba siempre en DEMO antes "
    "de replicar cualquier conclusion en la Terminal real."
)

controls = render_data_source_controls()

st.markdown("### ⚙️ Configuracion del backtest")
c1, c2, c3 = st.columns(3)
interval = c1.selectbox("Temporalidad", options=list(config.INTERVALS.keys()), index=list(config.INTERVALS.keys()).index("15m"))
strategy_name = c2.selectbox("Estrategia", options=STRATEGIES)
initial_cash = c3.number_input("Capital inicial", min_value=100.0, value=10_000.0, step=100.0)

c4, c5, c6 = st.columns(3)
commission_pct = c4.number_input("Comision por operacion (%)", min_value=0.0, value=0.1, step=0.01)
risk_pct = c5.number_input("Riesgo por operacion (%)", min_value=0.1, max_value=10.0, value=config.ICT_RISK_PCT_DEFAULT, step=0.1)
scalping_threshold = c6.slider(
    "Umbral de score (solo Scalping)", 0.1, 1.0, 0.5, 0.05, disabled=strategy_name != STRATEGIES[1]
)

run_clicked = st.button("▶️ Ejecutar backtest", type="primary", width="stretch")

if run_clicked:
    with st.spinner("Descargando historial profundo y ejecutando el backtest..."):
        df = get_ohlcv_deep(controls["source"], controls["symbol"], interval, exchange=controls["exchange"])
        if df.empty or len(df) < 200:
            st.warning("No hay suficiente historial para esta fuente/simbolo/temporalidad.")
        else:
            result = run_backtest(
                df, strategy_name,
                initial_cash=initial_cash, commission_pct=commission_pct,
                risk_pct=risk_pct, scalping_threshold=scalping_threshold,
            )
            st.session_state["backtest_result"] = result
            st.session_state["backtest_meta"] = {
                "symbol": controls["symbol"], "interval": interval, "strategy": strategy_name, "initial_cash": initial_cash,
            }

result = st.session_state.get("backtest_result")
meta = st.session_state.get("backtest_meta")

if result is None:
    st.info("Configura los parametros y pulsa **Ejecutar backtest** para ver resultados.")
else:
    stats = result["stats"]
    trades = result["trades"]
    equity = result["equity_curve"]["Equity"]

    st.markdown(f"### 📈 Resultados — {meta['strategy']} · {meta['symbol']} ({meta['interval']})")

    n_trades = int(stats.get("# Trades", 0) or 0)
    if 0 < n_trades < 20:
        st.warning(f"Solo {n_trades} operaciones en la muestra — resultado poco significativo estadisticamente, interpretar con cautela.")
    elif n_trades == 0:
        st.warning("La estrategia no genero ninguna operacion en este periodo/temporalidad. Prueba otro simbolo, temporalidad o estrategia.")

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Retorno", f"{stats.get('Return [%]', 0):+.2f}%")
    m2.metric("Sharpe Ratio", f"{stats.get('Sharpe Ratio', float('nan')):.2f}")
    m3.metric("Sortino Ratio", f"{stats.get('Sortino Ratio', float('nan')):.2f}")
    m4.metric("Max. Drawdown", f"{stats.get('Max. Drawdown [%]', 0):.2f}%")

    m5, m6, m7, m8 = st.columns(4)
    m5.metric("Win Rate", f"{stats.get('Win Rate [%]', float('nan')):.1f}%")
    m6.metric("# Operaciones", n_trades)
    m7.metric("Profit Factor", f"{stats.get('Profit Factor', float('nan')):.2f}")
    m8.metric("Expectativa", f"{stats.get('Expectancy [%]', float('nan')):+.2f}%")

    fig = equity_curve_chart(equity, initial_cash=meta["initial_cash"], title="Curva de equity")
    st.plotly_chart(fig, width="stretch")

    if not trades.empty:
        with st.expander(f"Ver operaciones ({len(trades)})"):
            display_cols = ["EntryTime", "ExitTime", "Size", "EntryPrice", "ExitPrice", "PnL", "ReturnPct", "Duration"]
            available_cols = [c for c in display_cols if c in trades.columns]
            st.dataframe(trades[available_cols], width="stretch", hide_index=True)

    st.markdown("### 📋 Tearsheet completo (quantstats)")
    if len(equity) < 5:
        st.caption("Muestra insuficiente para generar el tearsheet.")
    else:
        try:
            import quantstats as qs

            daily_equity = equity.resample("1D").last().dropna()
            returns = daily_equity.pct_change().dropna()
            if len(returns) < 5:
                st.caption("Periodo demasiado corto para un tearsheet diario significativo (se necesitan varios dias de historial).")
            else:
                with tempfile.NamedTemporaryFile(suffix=".html", delete=False) as tmp:
                    tmp_path = tmp.name
                qs.reports.html(returns, output=tmp_path, title=f"{meta['symbol']} — {meta['strategy']}")
                st.iframe(Path(tmp_path), height=900, width="stretch")
        except Exception as exc:
            st.error(f"No se pudo generar el tearsheet de quantstats: {exc}")
