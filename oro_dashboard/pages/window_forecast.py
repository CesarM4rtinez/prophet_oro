import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import streamlit as st

from core import config
from core.data import fetch_deep
from core.state import render_refresh_control
from core.window_forecast import (
    BAND_Q, LOCAL_TZ, PRIOR_NIGHTS, REPLAYS, SEED, WindowForecast, forecast_window, hourly_grid, verdict,
)
from core.supertrend import DEFAULT_FACTOR, DEFAULT_PERIOD, backtest_flip, current_state, supertrend
from ui.mpl_window import equity_chart, supertrend_chart, touch_ladder_chart, window_fan_chart
from ui.theme import COLORS, inject_css

inject_css()

st.title("🌙 Pronostico por Ventana Horaria (1h)")
st.caption(
    "Responde siempre: **¿que hara el oro entre ahora y el fin de la ventana?** (por defecto 9:00 p. m. → "
    "6:00 a. m., hora de El Salvador). Monte Carlo de noches historicas completas, escaladas por volatilidad y "
    "ponderadas por parecido al regimen actual, validado walk-forward contra la tasa base."
)

refresh_seconds = render_refresh_control()
st.sidebar.markdown("#### Ventana (hora El Salvador)")
start_h = int(st.sidebar.number_input("Inicio (hora 0-23)", min_value=0, max_value=23, value=21, key="wf_start"))
end_h = int(st.sidebar.number_input("Fin (hora 0-23)", min_value=0, max_value=23, value=6, key="wf_end"))
st.sidebar.markdown("#### Supertrend (TradingView)")
st_period = int(st.sidebar.number_input("Longitud ATR", min_value=1, max_value=100, value=DEFAULT_PERIOD, key="st_period"))
st_factor = float(st.sidebar.number_input("Factor", min_value=0.5, max_value=10.0, value=DEFAULT_FACTOR, step=0.5, key="st_factor"))
st_tf = st.sidebar.selectbox("Temporalidad Supertrend", ["1h", "15m", "5m"], index=0, key="st_tf")
st_cost = float(st.sidebar.number_input("Costo por operacion (USD/oz)", min_value=0.0, max_value=5.0, value=0.5, step=0.1, key="st_cost"))
CANDLES_SHOWN = 36
BAR_HOURS = {"1h": 1.0, "15m": 0.25, "5m": 5 / 60}


@st.cache_data(ttl=900, show_spinner=False, max_entries=16)
def _cached_forecast(last_ts: str, n_rows: int, start: int, end: int, _df: pd.DataFrame) -> WindowForecast | None:
    return forecast_window(_df, start, end)


def _local(ts) -> pd.DatetimeIndex:
    idx = pd.DatetimeIndex(ts)
    idx = idx.tz_localize("UTC") if idx.tz is None else idx
    return idx.tz_convert(LOCAL_TZ).tz_localize(None)


def _hour12(ts: pd.Timestamp) -> str:
    return ts.strftime("%I:%M %p").lstrip("0").replace("AM", "a. m.").replace("PM", "p. m.")


def _direction_has_edge(fc: WindowForecast) -> bool:
    v = fc.validation
    return bool(v) and v.get("skill", 0) > 0.01 and v.get("p_value", 1) < 0.05


@st.fragment(run_every=refresh_seconds or None)
def render() -> None:
    with st.spinner("Escaneando noches historicas..."):
        df = fetch_deep("1h")
        if df.empty:
            st.warning("No se pudieron descargar velas 1h ahora mismo.")
            return
        fc = _cached_forecast(str(df.index[-1]), len(df), start_h, end_h, df)
    if fc is None:
        st.warning("No hay suficiente historico 1h para esta ventana.")
        return

    edge = _direction_has_edge(fc)
    text, color_key = verdict(fc.p_above_now)
    hours_left = (fc.end_local - fc.anchor_utc.tz_convert(LOCAL_TZ)) / pd.Timedelta(hours=1)
    status = (
        "en curso" if fc.active
        else f"empieza a las {_hour12(fc.start_local)} ({fc.start_local.strftime('%d/%m')})"
    )
    q = fc.end_quantiles
    dir_line = (
        f"<b style='font-size:1.6rem;'>{text}</b> · P(cierra arriba del precio actual) {fc.p_above_now * 100:.0f} %"
        if edge else
        f"<b style='font-size:1.6rem;'>RANGO</b> · direccion sin ventaja validada (≈ moneda al aire: "
        f"{fc.p_above_now * 100:.0f} % arriba / {(1 - fc.p_above_now) * 100:.0f} % abajo)"
    )
    border = COLORS[color_key] if edge else COLORS["warning"]
    market = "fin de semana (spot cerrado, solo PAXG)" if fc.closed_market else "mercado abierto"
    st.markdown(
        f'<div class="oro-card" style="border-left:5px solid {border};">'
        f'<span style="opacity:0.75;">Ventana {_hour12(fc.start_local)} → {_hour12(fc.end_local)} '
        f'({fc.end_local.strftime("%d/%m")}) · {status} · {market} · quedan ~{hours_left:.0f} h</span><br>'
        f'{dir_line}<br>'
        f'<span style="font-size:1.15rem;">A las {_hour12(fc.end_local)}: mediana <b>${q[0.5]:,.0f}</b> · '
        f'50 % entre <b>${q[0.25]:,.0f}–${q[0.75]:,.0f}</b> · 80 % entre <b>${q[0.10]:,.0f}–${q[0.90]:,.0f}</b></span><br>'
        f'<span style="opacity:0.85;">Movimiento tipico de aqui al cierre: sube hasta ~${fc.up_ext_median:,.0f} y baja hasta '
        f'~${fc.down_ext_median:,.0f} desde el precio actual (rango total ~${fc.range_median:,.0f}).</span></div>',
        unsafe_allow_html=True,
    )

    g = hourly_grid(df).dropna()
    st_full = supertrend(g, st_period, st_factor)
    hist, st_hist = g.tail(CANDLES_SHOWN), st_full.tail(CANDLES_SHOWN)
    hist = hist.set_axis(_local(hist.index))
    st_hist = st_hist.set_axis(hist.index)
    fig = window_fan_chart(
        hist, st_hist, fc, _local(fc.step_times_utc),
        fc.start_local.tz_localize(None), fc.end_local.tz_localize(None),
        title=f"{config.SYMBOL_LABEL} 1h → {_hour12(fc.end_local)} (hora El Salvador) · Supertrend {st_period}/{st_factor:g}",
    )
    st.pyplot(fig, width="stretch")
    plt.close(fig)

    left, right = st.columns([1.1, 1])
    with left:
        fig = touch_ladder_chart(fc.touch_levels, fc.price_now, f"P(tocar nivel) antes de {_hour12(fc.end_local)}")
        st.pyplot(fig, width="stretch")
        plt.close(fig)
    with right:
        st.markdown("###### Lectura rapida")
        c1, c2 = st.columns(2)
        c1.metric("Precio actual", f"${fc.price_now:,.2f}")
        c2.metric(f"Mediana {_hour12(fc.end_local)}", f"${q[0.5]:,.2f}", f"{q[0.5] - fc.price_now:+,.2f}")
        c3, c4 = st.columns(2)
        c3.metric("Rango esperado", f"${fc.range_median:,.0f}")
        c4.metric("P(arriba del actual)", f"{fc.p_above_now * 100:.0f} %")
        if fc.p_above_window_open is not None:
            st.caption(
                f"Apertura de la ventana ({_hour12(fc.start_local)}): ${fc.window_open_price:,.2f} · "
                f"P(cerrar arriba de esa apertura) {fc.p_above_window_open * 100:.0f} %."
            )
        st.caption(
            f"Noches analizadas: {fc.n_nights} ({'fin de semana' if fc.closed_market else 'mercado abierto'}) · "
            f"muestra efectiva de noches parecidas {fc.n_eff:.0f} · peso de la tasa base {fc.beta * 100:.0f} % · "
            f"tasa base sin regimen P(arriba) {fc.base_p_up * 100:.0f} % · {REPLAYS:,} replays, seed {SEED}."
        )

    v = fc.validation
    st.markdown("---")
    st.markdown(f"##### ✅ ¿Cuanto confiar? Validacion walk-forward de la ventana {_hour12(fc.start_local)} → {_hour12(fc.end_local)}")
    if not v:
        st.info("Aun no hay suficientes noches para validar esta ventana.")
    else:
        st.caption(
            f"{v['n_test']} noches desde {v['test_from'].tz_convert(LOCAL_TZ).strftime('%d/%m/%Y')}, cada una pronosticada "
            "SOLO con noches anteriores (sin mirar el futuro)."
        )
        a, b, c, d = st.columns(4)
        a.metric("Banda 50 % contuvo", f"{v['cov50'] * 100:.0f} %")
        b.metric("Banda 80 % contuvo", f"{v['cov80'] * 100:.0f} %")
        c.metric("Banda 90 % contuvo", f"{v['cov90'] * 100:.0f} %")
        d.metric("Skill direccion vs tasa base", f"{v['skill'] * 100:+.1f} %")
        cal = pd.DataFrame(v["touch_calibration"], columns=["Nivel (σ de la ventana)", "P(toca) predicha", "Ocurrio realmente"])
        cal["P(toca) predicha"] = (cal["P(toca) predicha"] * 100).map("{:.0f} %".format)
        cal["Ocurrio realmente"] = (cal["Ocurrio realmente"] * 100).map("{:.0f} %".format)
        st.dataframe(cal, hide_index=True, width="stretch")
        dir_txt = (
            "**la direccion SI tiene ventaja estadistica** en esta ventana"
            if edge else
            "**la direccion NO supera a la tasa base** de forma significativa: usa el grafico para el RANGO y los "
            "niveles (bien calibrados), no para adivinar si sube o baja"
        )
        st.caption(
            f"Si la banda del 80 % contiene ~80 % de las noches, las bandas son confiables. Direccion: cuando el modelo "
            f"se inclino (P ≥ 55 % o ≤ 45 %) acerto {v['hits']}/{v['n_calls']} ({v['accuracy'] * 100:.0f} %), "
            f"p-valor binomial {v['p_value']:.3f}; Brier {v['brier_model']:.4f} vs tasa base {v['brier_base']:.4f} → {dir_txt}."
        )

    with st.expander("Metodo (por que este modelo y no otro)"):
        st.markdown(
            f"""
- **Historico:** las velas 1h de los ultimos ~2 años (el maximo que Yahoo entrega en 1h). Con ~500 noches de mercado
  abierto, el error estandar de una probabilidad es ~±2 puntos; datos de hace 10 años vienen de otro regimen de
  volatilidad y nivel de precio, y el escalado por volatilidad ya hace comparables las noches.
- **Monte Carlo por noches completas:** cada replay toma una noche real entera (mismo reloj de inicio y duracion), la
  escala a la volatilidad actual y la aplica al precio de ahora. Conserva el patron horario real (Asia, apertura de
  Londres) que un modelo vela-a-vela pierde.
- **Sin sobreentrenar:** solo 3 variables (momentum 24h, distancia a EMA 120h, volatilidad relativa) con un kernel de
  ancho fijo — nada se optimiza mirando el resultado. Los pesos se encogen hacia la tasa base con un prior de
  {PRIOR_NIGHTS:.0f} noches, y se separan noches de mercado abierto y de fin de semana.
- **Regresion lineal descartada para la direccion:** en la pagina *Proyeccion por Regresion* el R² fuera de muestra
  sale ~0; lo que si es estable y validable es la distribucion (rango, colas, probabilidad de tocar).
- Estimacion sobre PAXG-USD (proxy de XAU/USD). No es una orden ni una promesa: noticias pueden romper cualquier rango.
"""
        )


@st.fragment(run_every=refresh_seconds or None)
def render_supertrend() -> None:
    st.markdown("---")
    st.markdown(f"##### 🟢🔴 Supertrend {st_period}/{st_factor:g} ({st_tf}) — compra en verde, venta en rojo, cierre al cambiar de color")
    df = fetch_deep(st_tf)
    if df.empty or len(df) < 100:
        st.warning("No hay suficientes velas para el Supertrend ahora mismo.")
        return
    if st_tf == "1h":
        df = hourly_grid(df).dropna()
    s_tr = supertrend(df, st_period, st_factor)
    state = current_state(df, s_tr, closed_only=True)  # "Espere al cierre de los intervalos de tiempo"
    live_price = float(df["close"].iloc[-1])
    is_buy = state["trend"] == 1
    color = COLORS["bull"] if is_buy else COLORS["bear"]
    since_local = _local([state["since"]])[0] if state["since"] is not None else None
    move = (live_price - state["signal_close"]) * (1 if is_buy else -1) if state["signal_close"] else 0.0
    new_badge = " · 🔔 NUEVA SEÑAL en la ultima vela cerrada" if state["new_signal_on_last_bar"] else ""
    if since_local is None:
        st.info("Aun no hay cambio de color en el historico cargado.")
        return
    st.markdown(
        f'<div class="oro-card" style="border-left:5px solid {color};">'
        f'<b style="font-size:1.6rem;color:{color};">{"🟢 COMPRA" if is_buy else "🔴 VENTA"}</b>{new_badge}<br>'
        f'<span>Supertrend {"VERDE" if is_buy else "ROJO"} desde {since_local:%d/%m %I:%M %p} (hora El Salvador) '
        f'· señal a ${state["signal_close"]:,.2f} · precio ahora ${live_price:,.2f} · '
        f'resultado de la señal {move:+,.2f} USD/oz</span><br>'
        f'<span style="opacity:0.8;">Stop dinamico (linea Supertrend): ${state["line"]:,.2f}. Se cierra y se da vuelta '
        f'cuando una vela {st_tf} CIERRE {"debajo" if is_buy else "encima"} de esa linea.</span></div>',
        unsafe_allow_html=True,
    )

    shown = {"1h": 120, "15m": 160, "5m": 180}[st_tf]
    d_show = df.tail(shown).set_axis(_local(df.tail(shown).index))
    s_show = s_tr.tail(shown).set_axis(d_show.index)
    fig = supertrend_chart(d_show, s_show, BAR_HOURS[st_tf], f"{config.SYMBOL_LABEL} {st_tf} · Supertrend {st_period}/{st_factor:g}")
    st.pyplot(fig, width="stretch")
    plt.close(fig)

    bt = backtest_flip(df, s_tr, cost=st_cost)
    if bt["n"] == 0:
        return
    span = f"{_local([df.index[0]])[0]:%d/%m/%Y} → {_local([df.index[-1]])[0]:%d/%m/%Y}"
    st.markdown(f"###### Backtest de la regla ({span}, {bt['n']} operaciones, costo ${st_cost:.2f}/oz por operacion)")
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Resultado neto (1 oz)", f"${bt['net']:,.0f}")
    m2.metric("Profit factor", f"{bt['profit_factor']:.2f}")
    m3.metric("Operaciones ganadoras", f"{bt['win_rate'] * 100:.0f} %")
    m4.metric("Maxima caida", f"${bt['max_dd']:,.0f}")
    fig = equity_chart(bt["equity"], _local(bt["trades"]["salida"]), "Curva de resultados acumulados (USD por 1 oz)")
    st.pyplot(fig, width="stretch")
    plt.close(fig)
    verdict_txt = (
        "✅ La regla fue rentable en este periodo (profit factor > 1,2)." if bt["profit_factor"] > 1.2 else
        "⚠️ Rentabilidad marginal: el costo puede comerse la ventaja." if bt["profit_factor"] >= 1.0 else
        "❌ La regla PERDIO dinero en esta temporalidad: no conviene automatizarla aqui."
    )
    st.caption(
        f"{verdict_txt} Compras: ${bt['long_net']:,.0f} · Ventas: ${bt['short_net']:,.0f} · ganancia media ${bt['avg_win']:,.1f} "
        f"vs perdida media ${bt['avg_loss']:,.1f}. Entradas a la apertura de la vela siguiente a la señal (vela cerrada). "
        "Historico: 1h ≈ 2 años; 15m y 5m solo 60 dias (limite de Yahoo). Resultados pasados no garantizan los futuros."
    )
    last = bt["trades"].tail(8).iloc[::-1].copy()
    last["entrada"] = _local(last["entrada"]).strftime("%d/%m %I:%M %p")
    last["salida"] = _local(last["salida"]).strftime("%d/%m %I:%M %p")
    last = last.rename(columns={"precio_entrada": "precio entrada", "precio_salida": "precio salida", "pnl": "resultado USD/oz"})
    st.dataframe(last.round(2), hide_index=True, width="stretch")


render()
render_supertrend()
