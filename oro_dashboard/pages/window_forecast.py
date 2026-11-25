import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from core import config
from core.data import fetch_deep
from core.state import render_refresh_control
from core.window_forecast import (
    BAND_Q, LOCAL_TZ, PRIOR_NIGHTS, REPLAYS, SEED, WindowForecast, forecast_window, hourly_grid, verdict,
)
from ui.theme import COLORS, get_plotly_template, inject_css

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
CANDLES_SHOWN = 36


@st.cache_data(ttl=900, show_spinner=False, max_entries=16)
def _cached_forecast(last_ts: str, n_rows: int, start: int, end: int, _df: pd.DataFrame) -> WindowForecast | None:
    return forecast_window(_df, start, end)


def _local(ts) -> pd.DatetimeIndex:
    idx = pd.DatetimeIndex(ts)
    idx = idx.tz_localize("UTC") if idx.tz is None else idx
    return idx.tz_convert(LOCAL_TZ).tz_localize(None)


def _hour12(ts: pd.Timestamp) -> str:
    return ts.strftime("%I:%M %p").lstrip("0").replace("AM", "a. m.").replace("PM", "p. m.")


def _rgba(hex_color: str, alpha: float) -> str:
    h = hex_color.lstrip("#")
    return f"rgba({int(h[0:2], 16)},{int(h[2:4], 16)},{int(h[4:6], 16)},{alpha})"


def _direction_has_edge(fc: WindowForecast) -> bool:
    v = fc.validation
    return bool(v) and v.get("skill", 0) > 0.01 and v.get("p_value", 1) < 0.05


def fan_chart(df: pd.DataFrame, fc: WindowForecast) -> go.Figure:
    g = hourly_grid(df).dropna().tail(CANDLES_SHOWN)
    x_hist = _local(g.index)
    x_fut = _local(fc.step_times_utc)
    b = {q: fc.bands[i] for i, q in enumerate(BAND_Q)}
    fc_color = COLORS["series_forecast"]

    fig = go.Figure()
    fig.add_vrect(
        x0=fc.start_local.tz_localize(None), x1=fc.end_local.tz_localize(None),
        fillcolor=_rgba(COLORS["series_zone"], 0.10), line_width=0, layer="below",
        annotation_text="Ventana",
        annotation_position="top left", annotation_font_color=COLORS["text_secondary"],
    )
    fig.add_trace(go.Candlestick(
        x=x_hist, open=g["open"], high=g["high"], low=g["low"], close=g["close"],
        increasing_line_color=COLORS["bull"], increasing_fillcolor=COLORS["bull"],
        decreasing_line_color=COLORS["bear"], decreasing_fillcolor=COLORS["bear"],
        line_width=1, name="Precio 1h",
    ))
    for lo_q, hi_q, alpha, name in ((0.10, 0.90, 0.16, "80 % probable"), (0.25, 0.75, 0.34, "50 % probable")):
        fig.add_trace(go.Scatter(x=x_fut, y=b[lo_q], mode="lines", line=dict(width=0), showlegend=False, hoverinfo="skip"))
        fig.add_trace(go.Scatter(
            x=x_fut, y=b[hi_q], mode="lines", line=dict(width=0), fill="tonexty",
            fillcolor=_rgba(fc_color, alpha), name=name, hoverinfo="skip",
        ))
    fig.add_trace(go.Scatter(
        x=x_fut, y=b[0.5], mode="lines", line=dict(color=fc_color, width=2), name="Mediana",
        customdata=np.column_stack([b[0.10], b[0.25], b[0.75], b[0.90]]),
        hovertemplate=(
            "%{x|%d/%m %I:%M %p}<br>Mediana $%{y:,.2f}<br>50 %: $%{customdata[1]:,.0f}–$%{customdata[2]:,.0f}"
            "<br>80 %: $%{customdata[0]:,.0f}–$%{customdata[3]:,.0f}<extra></extra>"
        ),
    ))
    fig.add_hline(
        y=fc.price_now, line_width=1, line_dash="dash", line_color=COLORS["text_muted"],
        annotation_text=f"Ahora ${fc.price_now:,.2f}", annotation_position="bottom left",
        annotation_font_color=COLORS["text_secondary"],
    )
    x_end = x_fut[-1]
    for q, txt in ((0.90, "P90"), (0.5, "Mediana"), (0.10, "P10")):
        fig.add_annotation(
            x=x_end, y=b[q][-1], text=f"{txt} ${b[q][-1]:,.0f}", showarrow=False, xanchor="left", xshift=6,
            font=dict(color=COLORS["text_primary"] if q == 0.5 else COLORS["text_secondary"], size=12),
        )
    fig.update_layout(
        template=get_plotly_template(), height=560, xaxis_rangeslider_visible=False, hovermode="x unified",
        title=f"{config.SYMBOL_LABEL} 1h → {_hour12(fc.end_local)}",
        yaxis_title="Precio (USD)", margin=dict(l=10, r=110, t=70, b=90),
        xaxis=dict(range=[x_hist[0] - pd.Timedelta(minutes=30), x_fut[-1] + pd.Timedelta(minutes=30)]),
    )
    return fig


def ladder_chart(fc: WindowForecast) -> go.Figure:
    levels = fc.touch_levels
    labels = [f"${lv:,.0f}  ({lv - fc.price_now:+,.0f})" for lv, _ in levels]
    probs = [p * 100 for _, p in levels]
    colors = [COLORS["bull"] if lv > fc.price_now else COLORS["bear"] for lv, _ in levels]
    fig = go.Figure(go.Bar(
        x=probs, y=labels, orientation="h", marker_color=colors,
        text=[f"{p:.0f} %" for p in probs], textposition="outside",
        textfont=dict(color=COLORS["text_secondary"]),
        hovertemplate="Nivel %{y}<br>P(lo toca antes del fin) = %{x:.1f} %<extra></extra>",
    ))
    fig.update_layout(
        template=get_plotly_template(), height=420, showlegend=False,
        title=f"P(tocar nivel) antes de {_hour12(fc.end_local)}",
        xaxis=dict(range=[0, 105], ticksuffix=" %"), yaxis=dict(autorange="reversed"),
        margin=dict(l=10, r=30, t=60, b=40),
    )
    return fig


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

    st.plotly_chart(fan_chart(df, fc), width="stretch")

    left, right = st.columns([1.1, 1])
    with left:
        st.plotly_chart(ladder_chart(fc), width="stretch")
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


render()
