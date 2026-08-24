import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st

from core import config
from core.data import fetch_interval
from core.patterns import detect_abcd_patterns, detect_head_and_shoulders, detect_peaks_valleys
from core.timeutil import current_session_label, to_new_york_time
from core.state import render_refresh_control
from ui.charts import add_level_lines, add_pattern_lines, add_peaks_valleys, add_update_marker, candlestick_chart
from ui.theme import inject_css, render_data_status

inject_css()

st.title("🔍 Patrones Tecnicos y Armonicos")
st.caption(
    f"Deteccion sobre velas de 15m de {config.SYMBOL_LABEL}: picos/valles, patron armonico ABCD "
    "simplificado (razones Fibonacci 0.618-1.618 entre tramos X-A-B-D) y hombro-cabeza-hombro."
)

refresh_seconds = render_refresh_control()

oc1, oc2, oc3 = st.columns(3)
show_abcd = oc1.checkbox("Patron ABCD", value=True, key="patterns_show_abcd")
show_hs = oc2.checkbox("Hombro-Cabeza-Hombro", value=True, key="patterns_show_hs")
show_peaks = oc3.checkbox("Picos/Valles", value=True, key="patterns_show_peaks")


@st.fragment(run_every=refresh_seconds or None)
def render() -> None:
    df = fetch_interval("15m")
    if df.empty or len(df) < 40:
        st.warning("No hay suficientes velas de 15m para detectar patrones ahora mismo.")
        return

    close = df["close"].to_numpy(dtype=float)
    peaks, valleys = detect_peaks_valleys(close)
    head_shoulders = detect_head_and_shoulders(close, peaks)
    abcd = detect_abcd_patterns(close, valleys)

    render_data_status(to_new_york_time(df.index[-1]), current_session_label(df.index[-1]))

    entry = float(close[-1])
    stoploss, target1, target2 = entry * 0.99, entry * 1.01, entry * 1.02

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Precio actual (entry)", f"${entry:,.2f}")
    c2.metric("Patrones ABCD", len(abcd))
    c3.metric("Hombro-Cabeza-Hombro", len(head_shoulders))
    c4.metric("Picos / Valles", f"{len(peaks)} / {len(valleys)}")

    fig = candlestick_chart(df, title=f"{config.SYMBOL_LABEL} (15m) — Patrones Tecnicos y Armonicos")
    if show_peaks:
        add_peaks_valleys(fig, df, peaks, valleys)
    add_pattern_lines(fig, df, abcd if show_abcd else [], head_shoulders if show_hs else [])
    add_level_lines(fig, entry=entry, stoploss=stoploss, target1=target1, target2=target2)
    add_update_marker(fig, to_new_york_time(df.index[-1]))
    st.plotly_chart(fig, width="stretch")

    st.caption(
        f"Zonas de referencia sobre el ultimo cierre: Entry {entry:,.2f} · Stoploss {stoploss:,.2f} (-1%) · "
        f"Target 1 {target1:,.2f} (+1%) · Target 2 {target2:,.2f} (+2%)."
    )


render()
