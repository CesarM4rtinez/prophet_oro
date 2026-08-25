import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import streamlit as st

from core import config
from core.data import fetch_interval
from core.smc_zones import (
    atr,
    cached_multi_timeframe_probability,
    detect_order_blocks,
    label_structure,
    multi_timeframe_bias,
    zone_stats,
)
from core.state import render_refresh_control
from core.timeutil import current_session_label, to_new_york_time
from ui.charts import (
    add_bos_choch_labels,
    add_fibonacci_zone,
    add_fvg_zones,
    add_liquidity_sweeps,
    add_structure_labels,
    add_update_marker,
    add_zone_rectangles,
    candlestick_chart,
)
from ui.theme import inject_css, render_data_status

inject_css()

st.title("🧠 Estrategia Institucional (SMC)")
st.caption(
    "Smart Money Concepts / ICT multi-timeframe — sesgo en "
    f"{config.ICT_BIAS_INTERVAL}, estructura y Order Blocks en {config.ICT_STRUCTURE_INTERVAL}, "
    f"Fair Value Gaps y Fibonacci institucional en {config.ICT_ENTRY_INTERVAL}. Una ruptura de "
    "estructura solo cuenta como señal si el precio la RETESTEA despues (no en la barra de la "
    "ruptura misma) y hubo una barrida de liquidez confirmada cerca de la ruptura (patron AMD) — "
    "un spike aislado que revierte de inmediato queda 'sin confirmar', nunca como señal limpia."
)

refresh_seconds = render_refresh_control()


@st.fragment(run_every=refresh_seconds or None)
def render() -> None:
    df_bias = fetch_interval("1d")
    df_structure = fetch_interval("1h")
    df_entry = fetch_interval("5m")

    if (
        df_bias.empty or df_structure.empty or df_entry.empty
        or len(df_structure) < 60 or len(df_entry) < 60
    ):
        st.warning(
            f"No hay suficientes velas en alguna de las 3 temporalidades "
            f"({config.ICT_BIAS_INTERVAL}/{config.ICT_STRUCTURE_INTERVAL}/{config.ICT_ENTRY_INTERVAL}) ahora mismo."
        )
        return

    result = multi_timeframe_bias(df_bias, df_structure, df_entry)
    structure_stats = zone_stats(result["structure_zones"])

    render_data_status(to_new_york_time(df_entry.index[-1]), current_session_label(df_entry.index[-1]))

    bias_arrow = {"alcista": "↑", "bajista": "↓", "indefinido": "→"}[result["macro_bias"]]
    c1, c2, c3 = st.columns(3)
    c1.metric(f"Sesgo macro ({config.ICT_BIAS_INTERVAL})", f"{bias_arrow} {result['macro_bias'].capitalize()}")
    c2.metric("Precio actual", f"${result['current_price']:,.2f}")
    c3.metric("Entradas de alta probabilidad", len(result["high_probability_setups"]))

    if result["macro_mss"]:
        mss = result["macro_mss"]
        st.info(f"⚡ Ultimo Market Structure Shift ({config.ICT_BIAS_INTERVAL}): giro {mss['kind']} en ${mss['level']:,.2f}")

    if result["structure_sweeps"]:
        last_sweep = result["structure_sweeps"][-1]
        sweep_time = df_structure.index[last_sweep["idx"]]
        st.warning(
            f"🎣 Ultima barrida de liquidez detectada en {config.ICT_STRUCTURE_INTERVAL}: "
            f"{'bajista (barrio un maximo y revirtio)' if last_sweep['kind'] == 'bearish' else 'alcista (barrio un minimo y revirtio)'} "
            f"en ${last_sweep['level']:,.2f} ({sweep_time.strftime('%d/%m %H:%M')}). "
            "Un precio que perfora un maximo/minimo previo y cierra del lado contrario es tipicamente "
            "una trampa de stops, no continuacion — evitar entrar en la direccion de la mecha."
        )

    st.markdown("##### 📊 Probabilidad estadistica (confluencia 1h / 15m / 5m)")
    st.caption(
        "Compara la zona mas reciente de cada temporalidad con analogos historicos (misma direccion, "
        "altura de zona similar en proporcion al ATR) y con el desempeño de los ultimos 30 quiebres de "
        "estructura. Aproximacion estadistica generica, no replica ningun algoritmo comercial."
    )
    mtf_prob = cached_multi_timeframe_probability()
    pc1, pc2, pc3 = st.columns(3)
    for col, label in zip((pc1, pc2, pc3), ("1h", "15m", "5m")):
        entry = mtf_prob["per_timeframe"].get(label)
        if entry and entry["prob"]:
            fires = "🔥" * entry["prob"]["fires"] or "—"
            col.metric(f"{label} ({entry['kind']})", f"{entry['prob']['probability']:.0f}% {fires}", entry["prob"]["tier"])
        else:
            col.metric(label, "Sin datos")

    if mtf_prob["avg_probability"] is not None:
        align_msg = "✅ Alineadas" if mtf_prob["aligned"] else "⚠️ Sin alinear"
        st.markdown(f"**Probabilidad promedio: {mtf_prob['avg_probability']:.1f}%** · Temporalidades: {align_msg}")
        if not mtf_prob["aligned"]:
            st.caption("Regla de oro: nunca operar en base a una sola temporalidad — espera a que al menos 2 coincidan en direccion.")

    if result["high_probability_setups"]:
        st.markdown("##### 🎯 Entradas de alta probabilidad")
        st.caption(
            f"Solo se listan setups con order block CONFIRMADO (ya retesteado), patron AMD confirmado "
            f"(barrida de liquidez + quiebre) y RR >= 1:{config.ICT_MIN_RR:.0f}. Si esta tabla esta vacia, "
            "no hay ninguna entrada que cumpla las reglas — no es lo mismo que 'sin oportunidad', es "
            "'esperar' hasta que el precio retestee o aparezca una barrida confirmada."
        )
        setups_df = pd.DataFrame(
            [
                {
                    "Direccion": s["direccion"],
                    "Motivo": s["motivo"],
                    "Zona superior": s["zona_top"],
                    "Zona inferior": s["zona_bottom"],
                    "SL": s["sl"],
                    "TP": s["tp"],
                    "RR": round(s["rr"], 2),
                    "Confluencia prob.": (
                        "✅ Si" if mtf_prob["aligned"] and mtf_prob["aligned_kind"] == ("bullish" if s["direccion"] == "BUY" else "bearish") else "⚠️ No"
                    ),
                }
                for s in result["high_probability_setups"]
            ]
        )
        st.dataframe(setups_df, width="stretch", hide_index=True)
    else:
        st.caption(
            "Sin entradas que cumplan las reglas de oro en este momento (order block retesteado + "
            "barrida de liquidez confirmada + RR >= 1:2, alineado con el sesgo diario). La paciencia es la clave."
        )

    st.markdown("---")
    st.markdown(f"#### Estructura y Order Blocks ({config.ICT_STRUCTURE_INTERVAL})")
    oc1, oc2 = st.columns(2)
    show_sweeps = oc1.checkbox("Mostrar barridas de liquidez", value=True, key="smc_show_sweeps")
    show_structure_labels = oc2.checkbox("Mostrar estructura HH/HL/LL/LH", value=False, key="smc_show_structure")

    sc1, sc2, sc3 = st.columns(3)
    sc1.metric("Order blocks detectados", structure_stats["total"])
    sc2.metric("Tasa de continuacion", f"{structure_stats['continuo_pct']:.1f}%")
    sc3.metric("Tasa de fallo", f"{structure_stats['fallo_pct']:.1f}%")

    structure_label_info = label_structure(df_structure)
    structure_mss = structure_label_info["mss"]
    if structure_mss is not None and structure_mss["idx"] >= len(df_structure) - 10:
        mss_time = df_structure.index[structure_mss["idx"]]
        st.success(
            f"🔀 Cambio de estructura (CHoCH) reciente en {config.ICT_STRUCTURE_INTERVAL}: giro "
            f"{structure_mss['kind']} en ${structure_mss['level']:,.2f} ({mss_time.strftime('%d/%m %H:%M')}). "
            "Posible entrada temprana en la nueva direccion — buscar retest de la zona y barrida de "
            "liquidez (AMD) antes de operar, todavia no aparece en la tabla de entradas de alta probabilidad."
        )

    fig_structure = candlestick_chart(df_structure, title=f"{config.SYMBOL_LABEL} ({config.ICT_STRUCTURE_INTERVAL}) — Estructura")
    add_zone_rectangles(fig_structure, df_structure, result["structure_zones"])
    add_bos_choch_labels(fig_structure, df_structure, result["structure_zones"], mss=structure_label_info["mss"])
    if show_sweeps:
        add_liquidity_sweeps(fig_structure, df_structure, result["structure_sweeps"])
    if show_structure_labels:
        add_structure_labels(fig_structure, df_structure, structure_label_info["swings"][-12:])
    add_update_marker(fig_structure, to_new_york_time(df_structure.index[-1]))
    st.plotly_chart(fig_structure, width="stretch")

    if result["structure_zones"]:
        zones_df = pd.DataFrame(
            [
                {
                    "Tipo": "Alcista" if z["kind"] == "bullish" else "Bajista",
                    "Zona desde": df_structure.index[z["ob_idx"]],
                    "Ruptura": df_structure.index[z["break_idx"]],
                    "Superior": z["top"],
                    "Inferior": z["bottom"],
                    "SL": z["sl"],
                    "TP": z["tp"],
                    "Resultado": z["status"],
                }
                for z in reversed(result["structure_zones"])
            ]
        )
        st.dataframe(zones_df, width="stretch", hide_index=True)
        st.caption(
            "'sin_confirmar' = todavia no se sabe (falta retest o resolucion) · 'sin_datos' = no hay "
            "objetivo de liquidez calculable — ninguno de los dos es una señal operable."
        )

    st.markdown("---")
    st.markdown(f"#### Entrada — FVG y Fibonacci institucional ({config.ICT_ENTRY_INTERVAL})")
    ec1, ec2 = st.columns(2)
    show_fvg = ec1.checkbox("Mostrar Fair Value Gaps", value=False, key="smc_show_fvg")
    show_higher_tf_zones = ec2.checkbox(
        f"Mostrar Order Blocks de {config.ICT_STRUCTURE_INTERVAL} superpuestos", value=True, key="smc_show_higher_tf"
    )

    fig_entry = candlestick_chart(df_entry, title=f"{config.SYMBOL_LABEL} ({config.ICT_ENTRY_INTERVAL}) — Entrada")
    if show_higher_tf_zones:
        add_zone_rectangles(fig_entry, df_entry, result["structure_zones"], source_df=df_structure)
    if show_fvg:
        add_fvg_zones(fig_entry, df_entry, result["entry_fvgs"])
    if result["entry_fib"]:
        add_fibonacci_zone(fig_entry, result["entry_fib"])
    add_update_marker(fig_entry, to_new_york_time(df_entry.index[-1]))
    st.plotly_chart(fig_entry, width="stretch")
    if show_higher_tf_zones:
        st.caption(f"Las zonas sombreadas provienen de la temporalidad superior ({config.ICT_STRUCTURE_INTERVAL}), superpuestas sobre las velas de entrada.")

    if result["entry_fib"]:
        fib = result["entry_fib"]
        st.caption(
            f"Zona {'de descuento' if fib['bias'] == 'alcista' else 'premium'} "
            f"({fib['bias']}): {fib['zone_bottom']:,.2f} – {fib['zone_top']:,.2f} · "
            f"Equilibrio: {fib['equilibrium']:,.2f}"
        )


render()
