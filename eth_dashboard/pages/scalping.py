import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import streamlit as st

from core import config
from core.data_provider import get_ohlcv
from core.scalping import compute_indicators, detect_candle_patterns, monte_carlo_gbm, risk_levels, score_last
from core.smc_zones import current_session_label, to_new_york_time
from core.state import render_data_source_controls
from ui.charts import add_update_marker, candlestick_chart, monte_carlo_fan_chart
from ui.theme import COLORS, inject_css, render_data_status

inject_css()

st.title("⚡ Scorecard de Scalping + Proyeccion Monte Carlo")
st.caption(
    "Scorecard ponderado (EMA / RSI / MACD / Bollinger / Estocastico + volumen relativo), confluencia "
    "multi-timeframe y proyeccion de precio por simulacion Monte Carlo (movimiento geometrico browniano)."
)

controls = render_data_source_controls()


@st.fragment(run_every=controls["refresh_seconds"] or None)
def render() -> None:
    confluence_rows = []
    primary_df = primary_result = None

    for interval in config.INTERVALS:
        df = get_ohlcv(controls["source"], controls["symbol"], interval, exchange=controls["exchange"])
        if df.empty or len(df) < 60:
            continue
        result = score_last(compute_indicators(df))
        confluence_rows.append(
            {
                "Timeframe": interval,
                "Score": round(result["score"], 3),
                "Prob. Compra (%)": round(result["buy_probability"], 1),
                "Prob. Venta (%)": round(result["sell_probability"], 1),
                "Vol. relativo": round(result["rel_volume"], 2),
            }
        )
        if interval == controls["interval"]:
            primary_df, primary_result = df, result

    if primary_df is None:
        st.warning("No hay suficientes velas para calcular el scorecard en el intervalo seleccionado.")
        return

    direction = "buy" if primary_result["score"] >= 0 else "sell"
    levels = risk_levels(float(primary_df["close"].iloc[-1]), primary_result["atr14"], direction=direction)

    render_data_status(to_new_york_time(primary_df.index[-1]), current_session_label(primary_df.index[-1]))

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Score compuesto", f"{primary_result['score']:+.2f}")
    c2.metric("Prob. de compra", f"{primary_result['buy_probability']:.1f}%")
    c3.metric("Volumen relativo", f"{primary_result['rel_volume']:.2f}x")
    c4.metric("Direccion sugerida", "🟢 COMPRA" if direction == "buy" else "🔴 VENTA")

    fig = candlestick_chart(primary_df, title=f"{controls['symbol']} ({controls['interval']}) — Scalping")
    add_update_marker(fig, to_new_york_time(primary_df.index[-1]))
    for i, tp in enumerate(levels["targets"], start=1):
        fig.add_hline(
            y=tp, line_dash="dash", line_width=1, line_color=COLORS["bull"],
            annotation_text=f"TP{i}: {tp:,.2f}", annotation_font_color=COLORS["bull"], annotation_position="right",
        )
    fig.add_hline(
        y=levels["stoploss"], line_dash="dash", line_width=1.5, line_color=COLORS["bear"],
        annotation_text=f"SL: {levels['stoploss']:,.2f}", annotation_font_color=COLORS["bear"], annotation_position="right",
    )
    st.plotly_chart(fig, width="stretch")

    left, right = st.columns(2)
    with left:
        st.markdown("##### Confluencia multi-timeframe")
        st.dataframe(pd.DataFrame(confluence_rows), width="stretch", hide_index=True)

        st.markdown("##### Patrones de vela recientes")
        patterns = detect_candle_patterns(primary_df)
        if patterns:
            st.write(", ".join(f"`{p['name']}`" for p in patterns))
        else:
            st.caption("Sin patrones de vela relevantes en las ultimas velas.")

    with right:
        st.markdown("##### Proyeccion Monte Carlo (GBM)")
        close = primary_df["close"].to_numpy(dtype=float)
        n_steps = 30
        mc = monte_carlo_gbm(close, n_steps=n_steps)
        step = primary_df.index[-1] - primary_df.index[-2]
        future_times = [primary_df.index[-1] + step * i for i in range(n_steps + 1)]
        fig_mc = monte_carlo_fan_chart(future_times, mc["median"], mc["bands"], title="Bandas de confianza 50/80/95%")
        st.plotly_chart(fig_mc, width="stretch")


render()
