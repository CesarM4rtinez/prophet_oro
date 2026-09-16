import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import streamlit as st

from core import config
from core.data_provider import get_ohlcv
from core.ml_zone_classifier import predict_zone_probability, train_zone_classifier
from core.smc_zones import (
    atr,
    cached_multi_timeframe_probability,
    current_session_label,
    detect_liquidity_sweeps,
    detect_order_blocks,
    label_structure,
    multi_timeframe_bias,
    to_new_york_time,
    zone_stats,
)
from core.state import render_data_source_controls
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
    f"Fair Value Gaps y Fibonacci institucional en {config.ICT_ENTRY_INTERVAL}. "
    "Adaptado de Diario/4H-1H/15M-5M/1M a las temporalidades que soportan de forma confiable "
    "yfinance y ccxt por igual."
)

controls = render_data_source_controls()


@st.fragment(run_every=controls["refresh_seconds"] or None)
def render() -> None:
    df_bias = get_ohlcv(controls["source"], controls["symbol"], config.ICT_BIAS_INTERVAL, exchange=controls["exchange"])
    df_structure = get_ohlcv(controls["source"], controls["symbol"], config.ICT_STRUCTURE_INTERVAL, exchange=controls["exchange"])
    df_entry = get_ohlcv(controls["source"], controls["symbol"], config.ICT_ENTRY_INTERVAL, exchange=controls["exchange"])

    if df_bias.empty or df_structure.empty or df_entry.empty or len(df_structure) < 60 or len(df_entry) < 60:
        st.warning(
            f"No hay suficientes velas en alguna de las 3 temporalidades "
            f"({config.ICT_BIAS_INTERVAL}/{config.ICT_STRUCTURE_INTERVAL}/{config.ICT_ENTRY_INTERVAL}) "
            "para esta fuente/simbolo."
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
        st.info(f"⚡ Ultimo Market Structure Shift ({config.ICT_BIAS_INTERVAL}): giro {mss['kind']} en {mss['level']:,.2f}")

    st.markdown("##### 📊 Probabilidad estadistica (confluencia 1h / 15m / 5m)")
    st.caption(
        "Aproximacion estadistica: compara la zona mas reciente de cada temporalidad con analogos "
        "historicos (misma direccion, altura de zona similar en proporcion al ATR) y con el desempeño "
        "de los ultimos 30 quiebres de estructura. No es el algoritmo de ningun indicador comercial "
        "especifico — es un metodo equivalente, generalizado para funcionar en cualquier activo."
    )
    mtf_prob = cached_multi_timeframe_probability(controls["source"], controls["symbol"], controls["exchange"])
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
        st.caption("Solo se listan setups con patron AMD confirmado (manipulacion de liquidez + quiebre) y RR >= 1:2.")
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
                    "AMD confirmado": "Si" if s["amd_confirmado"] else "No",
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
            "Sin entradas que cumplan las reglas de oro en este momento (order block alineado + "
            "patron AMD confirmado + RR >= 1:2). La paciencia es la clave."
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

    fig_structure = candlestick_chart(df_structure, title=f"{controls['symbol']} ({config.ICT_STRUCTURE_INTERVAL}) — Estructura")
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

    st.markdown("---")
    st.markdown(f"#### Entrada — FVG y Fibonacci institucional ({config.ICT_ENTRY_INTERVAL})")
    ec1, ec2 = st.columns(2)
    show_fvg = ec1.checkbox("Mostrar Fair Value Gaps", value=False, key="smc_show_fvg")
    show_higher_tf_zones = ec2.checkbox(
        f"Mostrar Order Blocks de {config.ICT_STRUCTURE_INTERVAL} superpuestos", value=True, key="smc_show_higher_tf"
    )

    fig_entry = candlestick_chart(df_entry, title=f"{controls['symbol']} ({config.ICT_ENTRY_INTERVAL}) — Entrada")
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

    st.markdown("---")
    st.markdown("##### 🤖 Clasificador ML de zonas (experimental)")
    st.caption(
        "Segunda opinion independiente: un RandomForest entrenado sobre el historial real de order blocks "
        "de este simbolo/temporalidad, como complemento -no reemplazo- de la formula estadistica de arriba."
    )
    ml_zones = detect_order_blocks(df_entry, max_zones=500)
    ml_result = train_zone_classifier(df_entry)
    if not ml_result["trained"]:
        st.caption(f"Sin entrenar: {ml_result['reason']}")
    else:
        mc1, mc2, mc3, mc4 = st.columns(4)
        mc1.metric("Muestra (zonas)", ml_result["sample_size"])
        mc2.metric("Accuracy del modelo", f"{ml_result['accuracy']*100:.1f}%")
        mc3.metric("Baseline (clase mayoritaria)", f"{ml_result['baseline_accuracy']*100:.1f}%")
        mc4.metric("AUC", f"{ml_result['auc']:.2f}" if ml_result["auc"] is not None else "N/D")

        if ml_result["beats_baseline"]:
            st.success("✅ El modelo supera la baseline (predecir siempre la clase mayoritaria) — hay señal real en las features.")
        else:
            st.warning("⚠️ El modelo NO supera la baseline con esta muestra — tratar su prediccion como referencia debil, no como señal.")

        if ml_zones:
            current_zone = ml_zones[-1]
            atr_value = float(atr(df_entry).iloc[-1])
            ml_prob = predict_zone_probability(ml_result["model"], current_zone, atr_value)
            if ml_prob is not None:
                st.metric(
                    f"Probabilidad ML — zona activa ({'alcista' if current_zone['kind'] == 'bullish' else 'bajista'})",
                    f"{ml_prob:.0f}%",
                )

        with st.expander("Importancia de features"):
            importance_df = pd.DataFrame(
                {"Feature": list(ml_result["feature_importance"].keys()), "Importancia": list(ml_result["feature_importance"].values())}
            ).sort_values("Importancia", ascending=False)
            st.dataframe(importance_df, width="stretch", hide_index=True)


render()
