import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import matplotlib.pyplot as plt
import streamlit as st

from core import config
from core.calendar import IMPACTO_COLOR, events_naive
from core.data import fetch_interval
from core.probability import backtest_by_trend, backtest_targets, direction_levels
from core.smc_zones import cached_multi_timeframe_probability, detect_swings
from core.timeutil import current_session_label, to_new_york_time
from core.state import render_refresh_control
from ui.charts import add_calendar_events, add_level_lines, add_update_marker, candlestick_chart, grouped_bar_chart
from ui.mpl_charts import structure_multi_timeframe_chart, targets_price_chart
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

    st.markdown("###### Precio, Entry, Stoploss y Targets (compra y venta)")
    entry_now = float(close[-1])
    updated_label = f"{to_new_york_time(df.index[-1]).strftime('%d/%m/%Y %H:%M')} (NY)"

    pc1, pc2 = st.columns(2)
    for col, dir_key, dir_label in ((pc1, "compra", "COMPRA"), (pc2, "venta", "VENTA")):
        sl, t1, t2 = direction_levels(entry_now, 0.01, 0.01, 0.02, dir_key)
        with col:
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("Entry", f"${entry_now:,.2f}")
            m2.metric("Stoploss", f"${sl:,.2f}")
            m3.metric("Target 1", f"${t1:,.2f}")
            m4.metric("Target 2", f"${t2:,.2f}")
            fig_mpl = targets_price_chart(
                df, entry=entry_now, stoploss=sl, target1=t1, target2=t2,
                updated_at_label=updated_label, symbol_label=config.SYMBOL_LABEL,
                direction_label=dir_label, entry_label="Entry" if dir_key == "compra" else "Entry (venta)",
            )
            st.pyplot(fig_mpl, width="stretch")
            plt.close(fig_mpl)


render_conditional()

st.markdown("---")
st.markdown("##### 🧭 Estructura Multi-Temporalidad (5m / 15m / 1h)")
st.caption(
    "Misma confluencia 1h/15m/5m de la Estrategia Institucional (SMC): tendencia vigente, "
    "swings y niveles de Entrada/SL/TP de cada temporalidad, en un solo vistazo."
)


@st.fragment(run_every=refresh_seconds or None)
def render_structure_mtf() -> None:
    mtf_prob = cached_multi_timeframe_probability()

    panels = []
    for label in ("1h", "15m", "5m"):
        df_tf = fetch_interval(label)
        if df_tf.empty or len(df_tf) < 60:
            continue
        swings_df = detect_swings(df_tf, lookback=5).tail(150)
        info = mtf_prob["per_timeframe"].get(label)
        panels.append(
            {
                "label": label,
                "df": swings_df,
                "kind": info["kind"] if info else None,
                "entry": info["current_price"] if info else None,
                "sl": info["zone"]["sl"] if info else None,
                "tp": info["zone"]["tp"] if info else None,
            }
        )

    if not panels:
        st.warning("No hay suficientes velas en 1h/15m/5m para la estructura multi-temporalidad ahora mismo.")
        return

    veredicto = {"bullish": "alcista", "bearish": "bajista"}.get(mtf_prob["aligned_kind"]) if mtf_prob["aligned"] else None
    fig_mtf = structure_multi_timeframe_chart(panels, symbol_label=config.SYMBOL_LABEL, veredicto=veredicto)
    st.pyplot(fig_mtf, width="stretch")
    plt.close(fig_mtf)


render_structure_mtf()
