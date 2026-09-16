import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import streamlit as st

from core import config
from core.data_provider import get_ohlcv
from core.harmonics import detect_harmonic_patterns, swing_points
from core.patterns import detect_head_and_shoulders, detect_peaks_valleys
from core.smc_zones import current_session_label, to_new_york_time
from core.state import render_data_source_controls
from ui.charts import (
    add_forming_pattern,
    add_harmonic_pattern,
    add_level_lines,
    add_pattern_lines,
    add_peaks_valleys,
    add_support_resistance,
    add_update_marker,
    candlestick_chart,
)
from ui.theme import inject_css, render_data_status

inject_css()

st.title("🔍 Patrones Tecnicos y Armonicos")
st.caption(
    "Patrones armonicos clasicos (Gartley, Bat, Butterfly, Crab) por razones de Fibonacci publicas entre "
    "5 puntos de swing (X-A-B-C-D), soporte/resistencia, hombro-cabeza-hombro y picos/valles. "
    "Metodologia publica y verificada con datos reales — no replica ningun indicador comercial especifico."
)

controls = render_data_source_controls()

st.markdown("**Estilo de trading:**")
tc1, tc2 = st.columns([1, 1.5])
style = tc1.radio("Estilo", list(config.TRADING_STYLE_INTERVALS.keys()), horizontal=True, key="patterns_style", label_visibility="collapsed")
interval_options = config.TRADING_STYLE_INTERVALS[style]
interval = tc2.selectbox(
    "Temporalidad", interval_options, key=f"patterns_interval_{style}", label_visibility="collapsed"
)

oc1, oc2, oc3, oc4 = st.columns(4)
show_completed = oc1.checkbox("Patron completado", value=True, key="patterns_show_completed")
show_forming = oc2.checkbox("Patron en formacion (PRZ)", value=True, key="patterns_show_forming")
show_sr = oc3.checkbox("Soporte/Resistencia", value=True, key="patterns_show_sr")
show_peaks = oc4.checkbox("Picos/Valles", value=False, key="patterns_show_peaks")


@st.fragment(run_every=controls["refresh_seconds"] or None)
def render() -> None:
    df = get_ohlcv(controls["source"], controls["symbol"], interval, exchange=controls["exchange"])
    if df.empty or len(df) < 40:
        st.warning("No hay suficientes velas para detectar patrones en esta temporalidad/fuente.")
        return

    close = df["close"].to_numpy(dtype=float)
    peaks, valleys = detect_peaks_valleys(close)
    head_shoulders = detect_head_and_shoulders(close, peaks)
    harmonics = detect_harmonic_patterns(df)
    swings = swing_points(df)

    render_data_status(to_new_york_time(df.index[-1]), current_session_label(df.index[-1]))

    active = harmonics["completed"][-1] if harmonics["completed"] else None
    active_forming = harmonics["forming"][-1] if harmonics["forming"] else None

    c1, c2, c3, c4 = st.columns(4)
    if active:
        c1.metric("Patron activo", f"{active['name']} ({active['bias']})", active["status"])
        c2.metric("Entry", f"${active['entry']:,.2f}")
        c3.metric("Stop Loss", f"${active['sl']:,.2f}")
        c4.metric("Riesgo/Beneficio", f"1 : {active['rr']:.2f}" if active["rr"] else "N/D")
    elif active_forming:
        c1.metric("Patron candidato", f"{active_forming['name']} ({active_forming['bias']})", active_forming["status"])
        c2.metric("Zona Potencial de Reversion (PRZ)", f"${active_forming['prz_bottom']:,.2f} – ${active_forming['prz_top']:,.2f}")
        c3.metric("Puntos confirmados", "X · A · B · C")
        c4.metric("Riesgo/Beneficio", "Pendiente de D")
    else:
        st.info("Sin patrones armonicos detectados en esta temporalidad/fuente ahora mismo. La paciencia es la clave.")

    fig = candlestick_chart(df, title=f"{controls['symbol']} ({interval}) — Patrones armonicos")
    if show_sr:
        add_support_resistance(fig, df, swings)
    if show_peaks:
        add_peaks_valleys(fig, df, peaks, valleys)
    add_pattern_lines(fig, df, [], head_shoulders)
    if show_completed and active:
        add_harmonic_pattern(fig, df, active)
        add_level_lines(fig, entry=active["entry"], stoploss=active["sl"], target1=active["tp1"], target2=active["tp2"])
    if show_forming and active_forming:
        add_forming_pattern(fig, df, active_forming)
    add_update_marker(fig, to_new_york_time(df.index[-1]))
    st.plotly_chart(fig, width="stretch")

    all_patterns = [dict(p, estado="Completado") for p in harmonics["completed"]] + [
        dict(p, estado="En formacion") for p in harmonics["forming"]
    ]
    if all_patterns:
        with st.expander(f"Ver todos los patrones detectados ({len(all_patterns)})"):
            table = pd.DataFrame(
                [
                    {
                        "Patron": p["name"],
                        "Sesgo": p["bias"],
                        "Estado": p["estado"],
                        "Entry": p.get("entry"),
                        "SL": p.get("sl"),
                        "TP1": p.get("tp1"),
                        "TP2": p.get("tp2"),
                        "RR": round(p["rr"], 2) if p.get("rr") else None,
                    }
                    for p in all_patterns
                ]
            )
            st.dataframe(table, width="stretch", hide_index=True)

    st.caption(
        f"Ademas: {len(head_shoulders)} hombro-cabeza-hombro, {len(peaks)} picos, {len(valleys)} valles detectados."
    )


render()
