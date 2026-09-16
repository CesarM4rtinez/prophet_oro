import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st

from core.data_provider import get_ohlcv
from core.probability import backtest_by_trend, backtest_targets
from core.state import render_data_source_controls
from ui.charts import grouped_bar_chart, probability_bar_chart
from ui.theme import COLORS, inject_css

inject_css()

st.title("🎯 Probabilidad Historica de Targets")
st.caption(
    "Backtest por ventanas deslizantes: ¿cual nivel se alcanza primero, Target 1 (+1%), Target 2 (+2%) o Stoploss (-1%)? "
    "Global y condicional por regimen de tendencia (pendiente de la ventana)."
)

controls = render_data_source_controls()


@st.fragment(run_every=controls["refresh_seconds"] or None)
def render() -> None:
    df = get_ohlcv(controls["source"], controls["symbol"], controls["interval"], exchange=controls["exchange"])
    if df.empty or len(df) < 60:
        st.warning("No hay suficientes velas para este backtest en el intervalo/fuente seleccionado.")
        return

    close = df["close"].to_numpy(dtype=float)
    stats = backtest_targets(close)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Target 1 alcanzado", f"{stats['target1_pct']:.1f}%")
    c2.metric("Target 2 alcanzado", f"{stats['target2_pct']:.1f}%")
    c3.metric("Stoploss tocado", f"{stats['stoploss_pct']:.1f}%")
    c4.metric("Ventanas analizadas", f"{stats['sample_size']:,}")

    left, right = st.columns([1, 1.4])
    with left:
        fig = probability_bar_chart(
            ["Target 1", "Target 2", "Stoploss"],
            [stats["target1_pct"], stats["target2_pct"], stats["stoploss_pct"]],
            colors=[COLORS["bull"], COLORS["series_forecast"], COLORS["bear"]],
            title="Probabilidad global",
        )
        st.plotly_chart(fig, width="stretch")

    with right:
        summary = backtest_by_trend(close)
        series = {
            "Target 1": summary["Target1 (%)"],
            "Target 2": summary["Target2 (%)"],
            "Stoploss": summary["Stoploss (%)"],
        }
        colors = {"Target 1": COLORS["bull"], "Target 2": COLORS["series_forecast"], "Stoploss": COLORS["bear"]}
        fig2 = grouped_bar_chart(summary["Regimen"], series, colors, title="Probabilidad condicional por regimen")
        st.plotly_chart(fig2, width="stretch")

    st.dataframe(summary, width="stretch", hide_index=True)


render()
