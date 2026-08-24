import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import streamlit as st

from core import config
from core.data import fetch_interval
from core.prophet_model import train_and_forecast, trend_label
from core.timeutil import current_session_label, to_new_york_time
from core.state import render_refresh_control
from ui.charts import add_update_marker, forecast_chart
from ui.theme import inject_css, render_data_status

inject_css()

st.title("📈 Pronostico Predictivo con IA — Prophet")
st.caption(
    f"Historico diario (~1 año) de {config.SYMBOL_LABEL} + prediccion a 30 dias con banda de incertidumbre "
    "del 95%. El modelo se reentrena automaticamente cada ~15 min o cuando llegan velas nuevas."
)

refresh_seconds = render_refresh_control()


def _excel_bytes(merged: pd.DataFrame) -> bytes:
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        merged.to_excel(writer, index=False, sheet_name="Predictivo")
    return buffer.getvalue()


@st.fragment(run_every=refresh_seconds or None)
def render() -> None:
    history = fetch_interval("1d")

    if history.empty or len(history) < 30:
        st.warning("No se pudieron obtener suficientes datos historicos diarios para este simbolo.")
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

    fig = forecast_chart(history, forecast, title=f"{config.SYMBOL_LABEL} — Historico + Prediccion Prophet")
    add_update_marker(fig, to_new_york_time(history.index[-1]))
    st.plotly_chart(fig, width="stretch")

    with st.expander("Ver tabla de prediccion (ultimas 40 filas)"):
        table = forecast[["ds", "yhat", "yhat_lower", "yhat_upper"]].tail(40).rename(
            columns={"ds": "Fecha", "yhat": "Prediccion", "yhat_lower": "Margen inferior", "yhat_upper": "Margen superior"}
        )
        st.dataframe(table, width="stretch", hide_index=True)

    merged = pd.merge(
        forecast[["ds", "yhat", "yhat_lower", "yhat_upper"]],
        history.reset_index()[["time", "close"]].rename(columns={"time": "ds", "close": "y"}),
        on="ds",
        how="left",
    ).rename(
        columns={
            "ds": "Fecha", "y": "Historico", "yhat": "Prediccion_IA",
            "yhat_lower": "Margen_Inferior", "yhat_upper": "Margen_Superior",
        }
    )
    st.download_button(
        "⬇️ Descargar Excel (Power BI)",
        data=_excel_bytes(merged),
        file_name=f"{config.SYMBOL_LABEL}_Predictivo.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


render()
