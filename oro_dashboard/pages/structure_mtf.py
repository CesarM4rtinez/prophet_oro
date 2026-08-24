import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import streamlit as st

from core import config
from core.data import fetch_ohlcv
from core.state import render_refresh_control
from core.structure_mtf import analyze_multi_timeframe, detect_swings
from ui.charts import add_entry_sl_tp, add_swing_markers, candlestick_chart
from ui.theme import inject_css

inject_css()

st.title("🧭 Estructura Multi-Temporalidad (5m / 15m / 1h)")
st.caption(
    "Exige que 5m, 15m y 1h coincidan en direccion antes de dar una señal operable — si no coinciden, "
    "el veredicto es explicitamente 'sin confirmacion'. La probabilidad se mide sobre datos historicos: "
    "cuantas veces un quiebre de estructura (BOS) en 15m continuo, segun cuantas de las otras dos "
    "temporalidades (5m y 1h) ya estaban alineadas con esa direccion en ese momento."
)

refresh_seconds = render_refresh_control()

_TF_SPECS = {"5m": ("60d", "5m"), "15m": ("60d", "15m"), "1h": ("180d", "60m")}


@st.fragment(run_every=refresh_seconds or None)
def render() -> None:
    dfs = {}
    for tf, (period, interval) in _TF_SPECS.items():
        df = fetch_ohlcv(period, interval)
        if df.empty or len(df) < 2 * config.SWING_LOOKBACK + 10:
            st.warning(f"No hay suficientes velas de {tf} para analizar estructura ahora mismo.")
            return
        dfs[tf] = detect_swings(df)

    resultado = analyze_multi_timeframe(dfs)
    veredicto = resultado["veredicto"]
    direcciones = resultado["direcciones"]
    niveles = resultado["niveles"]

    if veredicto is None:
        divergentes = [tf for tf, d in direcciones.items() if d != max(set(direcciones.values()), key=list(direcciones.values()).count)]
        st.warning(
            f"⚠️ SIN CONFIRMACIÓN — las 3 temporalidades no coinciden en dirección. Diverge: {', '.join(divergentes)}. "
            "Ninguno de los niveles de abajo es una señal operable por si solo — esperar a que las 3 se alineen."
        )
    else:
        niv_15m = niveles["15m"]
        tp_txt = f"${niv_15m['take_profit']:,.2f}" if niv_15m and niv_15m["take_profit"] is not None else "sin liquidez identificada"
        tasa_2 = resultado["tasa_continuacion"].get(2) if len(resultado["tasa_continuacion"]) else None
        contexto = f" (contexto historico: {tasa_2}% de continuacion con 2/2 confirmaciones)" if tasa_2 is not None else ""
        st.success(
            f"✅ SEÑAL {veredicto.upper()} — 3/3 temporalidades alineadas. Usar niveles de 15m: "
            f"Entrada ${niv_15m['entrada']:,.2f} · SL ${niv_15m['stop_loss']:,.2f} · TP {tp_txt}{contexto}"
        )

    cols = st.columns(3)
    for col, tf in zip(cols, ("5m", "15m", "1h")):
        niv = niveles[tf]
        with col:
            if niv is None:
                st.metric(f"{tf}", "SIN DATO")
            else:
                st.metric(f"{tf} — {niv['tipo'].upper()}", f"${niv['entrada']:,.2f}", f"SL {niv['stop_loss']:,.2f}")

    if len(resultado["tasa_continuacion"]):
        st.markdown("##### Tasa historica de continuacion de un BOS de 15m, segun confirmaciones")
        etiquetas = {0: "0/2 — ninguna otra TF alineada", 1: "1/2 — una TF alineada", 2: "2/2 — 5m y 1h alineadas"}
        tabla = pd.DataFrame(
            {
                "Confirmaciones": [etiquetas[n] for n in resultado["tasa_continuacion"].index],
                "Continuacion (%)": resultado["tasa_continuacion"].values,
                "Muestras": resultado["muestras_por_confirmacion"].reindex(resultado["tasa_continuacion"].index).values,
            }
        )
        st.dataframe(tabla, width="stretch", hide_index=True)

    st.markdown("---")
    for tf in ("5m", "15m", "1h"):
        df_tf = resultado["dfs"][tf]
        niv = niveles[tf]
        reciente = df_tf.tail(150)
        fig = candlestick_chart(reciente, title=f"{config.SYMBOL_LABEL} · {tf} — tendencia vigente: {(niv['tipo'] if niv else 'sin dato').upper()}")
        add_swing_markers(fig, reciente)
        if niv is not None:
            add_entry_sl_tp(fig, entrada=niv["entrada"], stop_loss=niv["stop_loss"], take_profit=niv["take_profit"])
        st.plotly_chart(fig, width="stretch")


render()
