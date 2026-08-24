import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st

from core import config
from core.calendar import IMPACTO_COLOR, events_naive
from core.data import fetch_interval
from core.probability import backtest_by_trend, backtest_targets
from core.timeutil import current_session_label, to_new_york_time
from core.state import render_refresh_control
from ui.charts import add_calendar_events, add_level_lines, add_update_marker, candlestick_chart, grouped_bar_chart
from ui.theme import COLORS, inject_css, render_data_status

inject_css()

st.title("🎯 Probabilidad de Targets")
st.caption(
    "Backtest historico (Entry ±1%/±2% SL-TP) sobre ventanas de 30 velas: probabilidad global, "
    "cruzada con el calendario economico en la vista diaria, y condicional por regimen de tendencia."
)

refresh_seconds = render_refresh_control()

top1, top2 = st.columns([1, 1.4])
direction_label = top1.radio("Direccion", ["Compra", "Venta"], horizontal=True, key="prob_direction")
direction = "compra" if direction_label == "Compra" else "venta"
horizon_label = top2.radio(
    "Horizonte", ["Intradia (5m, 30 dias)", "Diario (1D, 2 años) + Calendario"], horizontal=True, key="prob_horizon"
)
is_daily = horizon_label.startswith("Diario")


@st.fragment(run_every=refresh_seconds or None)
def render_global() -> None:
    interval = "1d" if is_daily else "5m"
    df = fetch_interval(interval)
    if df.empty or len(df) < 60:
        st.warning("No hay suficientes velas para calcular probabilidad en este horizonte.")
        return

    close = df["close"].to_numpy(dtype=float)
    result = backtest_targets(close, direction=direction)

    render_data_status(to_new_york_time(df.index[-1]), current_session_label(df.index[-1]))

    entry = float(close[-1])
    if direction == "compra":
        stoploss, target1, target2 = entry * 0.99, entry * 1.01, entry * 1.02
    else:
        stoploss, target1, target2 = entry * 1.01, entry * 0.99, entry * 0.98

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Entry", f"${entry:,.2f}")
    c2.metric("Target 1 alcanzado", f"{result['target1_pct']:.1f}%")
    c3.metric("Target 2 alcanzado", f"{result['target2_pct']:.1f}%")
    c4.metric("Stoploss tocado", f"{result['stoploss_pct']:.1f}%")
    st.caption(f"Muestra: {result['sample_size']} ventanas de 30 velas ({interval}).")

    if is_daily:
        reciente = df.tail(25)
        fig = candlestick_chart(reciente, title=f"{config.SYMBOL_LABEL} — Probabilidad de Targets (1D) + Calendario Economico")
        events = events_naive()
        if not events.empty:
            eventos_semana = events[events["Fechas"] >= reciente.index.min()]
            add_calendar_events(fig, eventos_semana, IMPACTO_COLOR)
            st.caption(
                f"Eventos economicos relevantes para {config.SYMBOL_LABEL} en la ventana mostrada: {len(eventos_semana)}."
            )
        else:
            st.info("No se encontro el calendario economico (calendario_economico_ftmo/economic_calendar.xlsx).")
    else:
        fig = candlestick_chart(df, title=f"{config.SYMBOL_LABEL} (5m) — Probabilidad de Targets")

    add_level_lines(fig, entry=entry, stoploss=stoploss, target1=target1, target2=target2)
    add_update_marker(fig, to_new_york_time(df.index[-1]))
    st.plotly_chart(fig, width="stretch")


render_global()

st.markdown("---")
st.markdown("##### 📊 Probabilidad condicional por tipo de patron (15m)")
st.caption(
    "Clasifica cada ventana de 30 velas por pendiente (Alcista / Bajista / Lateral) y mide la "
    f"probabilidad de {direction_label.lower()} dentro de cada regimen."
)


@st.fragment(run_every=refresh_seconds or None)
def render_conditional() -> None:
    df = fetch_interval("15m")
    if df.empty or len(df) < 60:
        st.warning("No hay suficientes velas de 15m para el analisis condicional.")
        return

    close = df["close"].to_numpy(dtype=float)
    summary = backtest_by_trend(close, direction=direction)

    fig = grouped_bar_chart(
        summary["Regimen"],
        {
            "Target 1": summary["Target1 (%)"],
            "Target 2": summary["Target2 (%)"],
            "Stoploss": summary["Stoploss (%)"],
        },
        colors={"Target 1": COLORS["bull"], "Target 2": COLORS["series_forecast"], "Stoploss": COLORS["bear"]},
        title=f"Probabilidad condicional por regimen — {direction_label} (15m)",
    )
    st.plotly_chart(fig, width="stretch")
    st.dataframe(summary, width="stretch", hide_index=True)


render_conditional()
