import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import matplotlib.pyplot as plt
import pandas as pd
import streamlit as st

from core import config
from core.backtest import simulate_trades
from core.data import fetch_interval
from core.state import render_refresh_control
from ui.mpl_charts import equity_trades_chart, price_with_trades_chart, strategy_comparison_chart
from ui.theme import inject_css

inject_css()

st.title("🧪 Backtest de Estrategia")
st.caption(
    "Simulacion secuencial (un trade a la vez, sin solapar) de la regla Entry ±1%/±2% SL-TP: "
    "curva de capital, resultado de cada trade, marcadores de entrada/salida sobre el precio, "
    "y comparacion de retorno acumulado contra Buy & Hold."
)
st.caption(
    "⚠ Simplificacion: cada trade compromete el 100% del capital (sin apalancamiento ni "
    "position sizing fraccionado) y el cierre se decide solo con el precio de CIERRE de cada "
    "vela (no con mechas). Es una ilustracion de la forma de la curva, no una simulacion de "
    "gestion de riesgo real."
)

refresh_seconds = render_refresh_control()

top1, top2 = st.columns([1, 1.4])
direction_label = top1.radio("Direccion", ["Compra", "Venta"], horizontal=True, key="bt_direction")
direction = "compra" if direction_label == "Compra" else "venta"
interval = top2.selectbox("Temporalidad", list(config.INTERVALS.keys()), index=list(config.INTERVALS.keys()).index("1h"), key="bt_interval")


@st.fragment(run_every=refresh_seconds or None)
def render() -> None:
    df = fetch_interval(interval)
    if df.empty or len(df) < 60:
        st.warning("No hay suficientes velas para simular la estrategia en esta temporalidad.")
        return

    result = simulate_trades(df, direction=direction)
    trades = result["trades"]
    if not trades:
        st.warning("No se genero ningun trade con estos parametros.")
        return

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Capital final", f"${result['final_capital']:,.0f}", f"{result['total_return_pct']:+.1f}%")
    c2.metric("Trades ejecutados", result["n_trades"])
    c3.metric("Win rate", f"{result['win_rate_pct']:.1f}%")
    c4.metric("Buy & Hold (mismo periodo)", f"{result['buy_hold_return_pct']:+.1f}%")

    fig1 = equity_trades_chart(trades, result["equity"], result["initial_capital"], config.SYMBOL_LABEL)
    st.pyplot(fig1, width="stretch")
    plt.close(fig1)

    fig2 = price_with_trades_chart(df, trades, config.SYMBOL_LABEL)
    st.pyplot(fig2, width="stretch")
    plt.close(fig2)

    strategy_dates = [t["exit_time"] for t in trades]
    strategy_cum_pct = [(e / result["initial_capital"] - 1) * 100 for e in result["equity"]]
    buy_hold_cum_pct = (df["close"] / df["close"].iloc[0] - 1) * 100

    fig3 = strategy_comparison_chart(
        strategy_dates, {"Estrategia (simulada)": strategy_cum_pct},
        symbol_label=config.SYMBOL_LABEL,
    )
    ax = fig3.axes[0]
    ax.plot(df.index, buy_hold_cum_pct, color="#898781", linewidth=1.2, label="Buy & Hold")
    ax.legend(fontsize=8, loc="upper left")
    st.pyplot(fig3, width="stretch")
    plt.close(fig3)

    with st.expander(f"Ver log de trades ({len(trades)})"):
        trades_df = pd.DataFrame(
            [
                {
                    "Entrada": t["entry_time"], "Salida": t["exit_time"],
                    "Precio entrada": t["entry_price"], "Precio salida": t["exit_price"],
                    "Resultado": t["result"], "P/L (%)": round(t["pnl_pct"] * 100, 2),
                }
                for t in reversed(trades)
            ]
        )
        st.dataframe(trades_df, width="stretch", hide_index=True)


render()
