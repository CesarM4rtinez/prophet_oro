import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import streamlit as st

from core import config
from core.data_provider import get_ohlcv
from core.prophet_model import train_and_forecast, trend_label
from core.smc_zones import atr, current_session_label, detect_order_blocks, to_new_york_time, zone_probability
from core.state import render_data_source_controls
from ui.charts import add_update_marker, forecast_chart
from ui.theme import inject_css, render_data_status

inject_css()

st.title("📈 Pronostico Predictivo con IA — Prophet")
st.caption(
    "Historico diario (~1 año) + prediccion a 30 dias con banda de incertidumbre del 95%. "
    "El modelo se reentrena automaticamente cada ~15 min o cuando llegan velas nuevas."
)

controls = render_data_source_controls()


@st.fragment(run_every=controls["refresh_seconds"] or None)
def render() -> None:
    history = get_ohlcv(controls["source"], controls["symbol"], "1d", exchange=controls["exchange"])

    if history.empty or len(history) < 30:
        st.warning("No se pudieron obtener suficientes datos historicos diarios para este simbolo/fuente.")
        return

    with st.spinner("Entrenando modelo Prophet..."):
        forecast = train_and_forecast(history, horizon_periods=30, freq="D")

    label, trend = trend_label(forecast)

    render_data_status(to_new_york_time(history.index[-1]), current_session_label(history.index[-1]))

    last_close = float(history["close"].iloc[-1])
    change_24h = (last_close / float(history["close"].iloc[-2]) - 1) * 100 if len(history) > 1 else 0.0
    forecast_30d = float(forecast["yhat"].iloc[-1])
    upside = (forecast_30d / last_close - 1) * 100

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Precio actual", f"${last_close:,.2f}", f"{change_24h:+.2f}% (1d)")
    c2.metric("Prediccion a 30 dias", f"${forecast_30d:,.2f}", f"{upside:+.2f}%")
    c3.metric("Señal de tendencia", label.split(" ", 1)[1])
    c4.metric("Pendiente media (10p)", f"{trend:+.2f}")

    fig = forecast_chart(history, forecast, title=f"{controls['symbol']} — Historico + Prediccion Prophet")
    add_update_marker(fig, to_new_york_time(history.index[-1]))
    st.plotly_chart(fig, width="stretch")

    with st.expander("Ver tabla de prediccion (ultimas 40 filas)"):
        table = forecast[["ds", "yhat", "yhat_lower", "yhat_upper"]].tail(40).rename(
            columns={"ds": "Fecha", "yhat": "Prediccion", "yhat_lower": "Margen inferior", "yhat_upper": "Margen superior"}
        )
        st.dataframe(table, width="stretch", hide_index=True)

    st.markdown("---")
    st.markdown("##### 🧠 Confluencia: zona institucional mas cercana")
    st.caption(
        f"Complemento estadistico (no forma parte del modelo Prophet): probabilidad de continuacion "
        f"de la zona SMC mas reciente en {config.ICT_ENTRY_INTERVAL}, comparada con analogos historicos."
    )
    df_entry = get_ohlcv(controls["source"], controls["symbol"], config.ICT_ENTRY_INTERVAL, exchange=controls["exchange"])
    if not df_entry.empty and len(df_entry) >= 60:
        zones = detect_order_blocks(df_entry, max_zones=200)
        if zones:
            current_zone = zones[-1]
            atr_value = float(atr(df_entry).iloc[-1])
            prob = zone_probability(zones, current_zone, atr_value)
            zc1, zc2, zc3 = st.columns(3)
            zc1.metric("Zona activa", "Alcista" if current_zone["kind"] == "bullish" else "Bajista")
            if prob:
                fires = "🔥" * prob["fires"] or "—"
                zc2.metric("Probabilidad de continuacion", f"{prob['probability']:.0f}% {fires}", prob["tier"])
                zc3.metric("Tasa de retest", f"{prob['retest_pct']:.0f}%")
                if prob["low_retest_warning"]:
                    st.caption("⚠️ Tasa de retest baja: es probable que el precio distribuya directo, sin retroceso claro para entrar.")
            else:
                zc2.metric("Probabilidad de continuacion", "Sin muestra suficiente")
        else:
            st.caption("Sin order blocks detectados en la temporalidad de entrada para este simbolo/fuente.")


render()
