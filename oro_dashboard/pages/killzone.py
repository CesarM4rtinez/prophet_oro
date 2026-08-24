import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import streamlit as st

from core import config
from core.calendar import IMPACTO_COLOR, events_in_timezone
from core.data import fetch_ohlcv
from core.state import render_refresh_control
from ui.charts import add_calendar_events, add_killzone_window, add_level_lines, candlestick_chart
from ui.theme import inject_css

inject_css()

st.title("🕗 Plan de Trading — Killzone de Nueva York")
st.caption(
    f"Mide que pasa DENTRO de la killzone de Nueva York ({config.KILLZONE_NY_START}-{config.KILLZONE_NY_END} "
    f"{config.KILLZONE_TZ}, ventana de mayor liquidez del dia) y arma un ticket Entrada/SL/TP fijo para "
    "colocar y dejar corriendo sin revisar el grafico hasta el cierre de la killzone."
)

refresh_seconds = render_refresh_control()


def _sesion_ny_vigente_o_proxima(ahora_ny: pd.Timestamp) -> tuple[pd.Timestamp, pd.Timestamp]:
    dia = ahora_ny.normalize()
    while True:
        apertura = dia + pd.Timedelta(hours=8)
        cierre = dia + pd.Timedelta(hours=12)
        if dia.dayofweek < 5 and ahora_ny <= cierre:
            return apertura, cierre
        dia += pd.Timedelta(days=1)


@st.fragment(run_every=refresh_seconds or None)
def render() -> None:
    data_1h = fetch_ohlcv("180d", "60m")
    if data_1h.empty or len(data_1h) < 48:
        st.warning("No hay suficientes velas de 1h para calcular el plan de killzone.")
        return

    data_1h = data_1h.copy()
    data_1h.index = (
        data_1h.index.tz_convert(config.KILLZONE_TZ)
        if data_1h.index.tz is not None
        else data_1h.index.tz_localize("UTC").tz_convert(config.KILLZONE_TZ)
    )

    resultados = {"Target1": 0, "Target2": 0, "Stoploss": 0, "Total": 0}
    for dia, grupo in data_1h.groupby(data_1h.index.date):
        if pd.Timestamp(dia).dayofweek >= 5:
            continue
        sesion = grupo.between_time(config.KILLZONE_NY_START, config.KILLZONE_NY_END)
        if len(sesion) < 2:
            continue
        apertura = float(sesion["close"].iloc[0])
        sl, t1, t2 = apertura * 0.99, apertura * 1.01, apertura * 1.02
        resultado = None
        for precio in sesion["close"].iloc[1:]:
            if precio <= sl:
                resultado = "Stoploss"
                break
            if precio >= t2:
                resultado = "Target2"
                break
            if precio >= t1:
                resultado = "Target1"
                break
        if resultado:
            resultados[resultado] += 1
        resultados["Total"] += 1

    total = resultados["Total"] or 1
    p_stop = resultados["Stoploss"] / total * 100
    p_t1 = resultados["Target1"] / total * 100
    p_t2 = resultados["Target2"] / total * 100
    p_sin_tocar = 100 - p_stop - p_t1 - p_t2

    ahora_ny = pd.Timestamp.now(tz=config.KILLZONE_TZ)
    apertura_sesion, cierre_sesion = _sesion_ny_vigente_o_proxima(ahora_ny)
    sesion_en_curso = apertura_sesion <= ahora_ny <= cierre_sesion

    entrada = float(data_1h["close"].iloc[-1])
    entrada_ts = data_1h.index[-1]
    horas_hasta_apertura = (apertura_sesion - ahora_ny).total_seconds() / 3600
    stoploss_s, target1_s, target2_s = entrada * 0.99, entrada * 1.01, entrada * 1.02

    st.markdown(
        f"**Sesion:** {apertura_sesion.strftime('%A %d/%m/%Y %H:%M')} → {cierre_sesion.strftime('%H:%M')} "
        f"({config.KILLZONE_TZ}) — {'🟢 en curso ahora mismo' if sesion_en_curso else '⏳ proxima sesion (aun no abre)'}"
    )
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Entrada" + (" actual" if sesion_en_curso else " de referencia"), f"${entrada:,.2f}", f"dato de {entrada_ts.strftime('%d/%m %H:%M')}")
    c2.metric("Stop Loss (-1%)", f"${stoploss_s:,.2f}")
    c3.metric("Target 1 (+1%)", f"${target1_s:,.2f}", f"historico: {p_t1:.1f}%")
    c4.metric("Target 2 (+2%)", f"${target2_s:,.2f}", f"historico: {p_t2:.1f}%")
    st.caption(
        f"Sobre {resultados['Total']} sesiones historicas: Target1 {p_t1:.1f}% · Target2 {p_t2:.1f}% · "
        f"Stoploss {p_stop:.1f}% · ninguno tocado {p_sin_tocar:.1f}%."
    )
    if not sesion_en_curso and horas_hasta_apertura > 1:
        st.warning(
            f"Faltan {horas_hasta_apertura:.1f}h para que abra la killzone. Esta Entrada/SL/TP son de "
            "referencia — vuelve a abrir esta pagina cerca de la apertura para recalcularlos con el "
            "precio real (PAXG-USD cotiza 24/7, el oro real no; el precio puede moverse mientras tanto)."
        )
    st.caption(
        "Regla de salida: si al cierre de la killzone ninguno se tocó, cerrar manualmente a mercado — "
        "no dejar la posicion abierta para la tarde de NY ni la sesion siguiente."
    )

    eventos_dia = events_in_timezone(config.KILLZONE_TZ)
    if not eventos_dia.empty:
        eventos_dia = eventos_dia[eventos_dia["Fechas"].dt.date == apertura_sesion.date()].sort_values("Fechas")
    if len(eventos_dia):
        with st.expander(f"📅 Eventos economicos ese dia ({apertura_sesion.date()}): {len(eventos_dia)}", expanded=True):
            st.dataframe(
                eventos_dia[["Fechas", "Descripción", "Impacto"]].assign(Fechas=lambda d: d["Fechas"].dt.strftime("%H:%M")),
                width="stretch", hide_index=True,
            )
    else:
        st.caption(f"Sin eventos economicos relevantes para {config.SYMBOL_LABEL} ese dia.")

    reciente = data_1h.tail(5 * 24)
    fig = candlestick_chart(reciente, title=f"{config.SYMBOL_LABEL} — Plan de Trading Killzone NY ({apertura_sesion.strftime('%d/%m/%Y')})")
    add_level_lines(fig, entry=entrada, stoploss=stoploss_s, target1=target1_s, target2=target2_s)
    add_killzone_window(fig, apertura_sesion, cierre_sesion)
    if len(eventos_dia):
        add_calendar_events(fig, eventos_dia, IMPACTO_COLOR)
    st.plotly_chart(fig, width="stretch")


render()
