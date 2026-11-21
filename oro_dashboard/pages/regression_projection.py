import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from core import config
from core.data import fetch_deep
from core.regression_projection import (
    HORIZONS, MC_REPLAYS, MC_SEED, STOP_ATR, TARGET_ATR, Projection, project, signal_label,
)
from core.state import render_refresh_control
from core.timeutil import current_session_label, to_new_york_time
from ui.theme import COLORS, get_plotly_template, inject_css, render_data_status

inject_css()

st.title("📉 Proyeccion por Regresion (5m · 15m · 1h)")
st.caption(
    "Proyeccion estadistica de las proximas velas de XAU/USD combinando tres modelos: "
    "**Ridge (L2) multi-horizonte** con terminos polinomicos y de serie de tiempo, "
    "**regresion logistica** P(sube) y **Monte Carlo 'Time Machine'** (5 000 replays con velas reales "
    "del mismo horario). Las bandas salen de los cuantiles de los errores fuera de muestra "
    "(regresion cuantilica conformal). Se recalcula sola con el auto-refresco."
)

refresh_seconds = render_refresh_control()

HORIZON_TEXT = {"5m": "proxima 1 h (12 velas)", "15m": "proximas 4 h (16 velas)", "1h": "proximas 24 h (24 velas)"}
VISIBLE_BARS = {"5m": 96, "15m": 96, "1h": 96}


@st.cache_data(ttl=600, show_spinner=False, max_entries=12)
def _cached_projection(label: str, last_ts: str, n_rows: int, _df: pd.DataFrame) -> Projection | None:
    # `last_ts` + `n_rows` son la llave del cache: el modelo se reentrena solo cuando
    # llega una vela nueva, no en cada auto-refresco.
    return project(_df, label)


def _ny_index(index) -> pd.DatetimeIndex:
    idx = pd.DatetimeIndex(index)
    idx = idx.tz_localize("UTC") if idx.tz is None else idx.tz_convert("UTC")
    return (idx + pd.Timedelta(hours=config.NY_UTC_OFFSET_HOURS)).tz_localize(None)


def _hex_rgba(hex_color: str, alpha: float) -> str:
    h = hex_color.lstrip("#")
    return f"rgba({int(h[0:2], 16)},{int(h[2:4], 16)},{int(h[4:6], 16)},{alpha})"


def projection_chart(df: pd.DataFrame, proj: Projection) -> go.Figure:
    hist = df.tail(VISIBLE_BARS[proj.label])
    x_hist = _ny_index(hist.index)
    x_fut = _ny_index(proj.future_index)
    q05, q25, q50, q75, q95 = proj.reg_bands
    fc = COLORS["series_forecast"]

    fig = go.Figure()
    fig.add_trace(go.Candlestick(
        x=x_hist, open=hist["open"], high=hist["high"], low=hist["low"], close=hist["close"],
        increasing_line_color=COLORS["bull"], increasing_fillcolor=COLORS["bull"],
        decreasing_line_color=COLORS["bear"], decreasing_fillcolor=COLORS["bear"],
        line_width=1, name="Precio",
    ))
    # Bandas: 5-95 % (clara) y 25-75 % (mas densa). Se dibuja borde inferior y luego
    # el superior con fill="tonexty".
    for lo, hi, alpha, name in ((q05, q95, 0.14, "Banda 90 % (5-95)"), (q25, q75, 0.30, "Banda 50 % (25-75)")):
        fig.add_trace(go.Scatter(x=x_fut, y=lo, mode="lines", line=dict(width=0), showlegend=False, hoverinfo="skip"))
        fig.add_trace(go.Scatter(
            x=x_fut, y=hi, mode="lines", line=dict(width=0), fill="tonexty",
            fillcolor=_hex_rgba(fc, alpha), name=name, hoverinfo="skip",
        ))
    fig.add_trace(go.Scatter(
        x=x_fut, y=q50, mode="lines+markers", line=dict(color=fc, width=2), marker=dict(size=4),
        name="Regresion (mediana)", hovertemplate="%{x|%d/%m %H:%M}<br>Regresion: $%{y:,.2f}<extra></extra>",
    ))
    if proj.mc:
        fig.add_trace(go.Scatter(
            x=x_fut, y=proj.mc["bands"][2], mode="lines", line=dict(color=COLORS["series_zone"], width=2, dash="dot"),
            name="Monte Carlo (mediana)", hovertemplate="%{x|%d/%m %H:%M}<br>Monte Carlo: $%{y:,.2f}<extra></extra>",
        ))
    fig.add_hline(
        y=proj.last_close, line_width=1, line_dash="dash", line_color=COLORS["text_muted"],
        annotation_text=f"Ultimo ${proj.last_close:,.2f}", annotation_position="bottom left",
        annotation_font_color=COLORS["text_secondary"],
    )
    fig.add_vline(x=x_fut[0], line_width=1, line_dash="dot", line_color=COLORS["series_marker"])
    fig.update_layout(
        template=get_plotly_template(), height=560, xaxis_rangeslider_visible=False,
        title=f"{config.SYMBOL_LABEL} ({proj.label}) — proyeccion {HORIZON_TEXT[proj.label]}",
        hovermode="x unified", yaxis_title="Precio (USD)", xaxis_title="Hora NY",
    )
    return fig


def coef_chart(proj: Projection) -> go.Figure:
    coefs = proj.coefs.head(8).iloc[::-1]
    colors = [COLORS["bull"] if v > 0 else COLORS["bear"] for v in coefs.values]
    fig = go.Figure(go.Bar(
        x=coefs.values, y=coefs.index, orientation="h", marker_color=colors,
        hovertemplate="%{y}: %{x:+.3f}<extra></extra>",
    ))
    fig.update_layout(
        template=get_plotly_template(), height=300, margin=dict(l=10, r=20, t=40, b=30),
        title=f"Peso de cada variable (Ridge, horizonte {proj.horizon} velas)", showlegend=False,
    )
    return fig


def _pct(x: float) -> str:
    return "—" if x is None or not np.isfinite(x) else f"{x * 100:.1f} %"


def render_detail(df: pd.DataFrame, proj: Projection) -> None:
    st.plotly_chart(projection_chart(df, proj), width="stretch")

    m = proj.metrics
    end_med = proj.reg_bands[2, -1]
    move = (end_med / proj.last_close - 1) * 100
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Precio proyectado (mediana)", f"${end_med:,.2f}", f"{move:+.2f} %")
    c2.metric("Rango 90 % al cierre", f"${proj.reg_bands[0, -1]:,.0f} – ${proj.reg_bands[4, -1]:,.0f}")
    c3.metric("P(sube) consenso", _pct(proj.consensus_p_up))
    c4.metric("ATR (14)", f"${proj.atr:,.2f}")

    st.markdown("###### Probabilidad de que el precio cierre arriba al final del horizonte")
    prob_rows = [
        ("Ridge L2 + residuos fuera de muestra", proj.reg_p_up),
        ("Regresion logistica P(Y=1)", proj.logit_p_up),
    ]
    if proj.mc:
        prob_rows.append((f"Monte Carlo ({proj.mc['replays']:,} replays, seed {proj.mc['seed']})", proj.mc["p_up"]))
    prob_rows.append(("**Consenso (promedio)**", proj.consensus_p_up))
    st.dataframe(
        pd.DataFrame({"Modelo": [r[0].replace("**", "") for r in prob_rows], "P(sube)": [_pct(r[1]) for r in prob_rows],
                      "P(baja)": [_pct(1 - r[1]) for r in prob_rows]}),
        hide_index=True, width="stretch",
    )

    if proj.mc:
        st.markdown(
            f"###### Time Machine — stop {STOP_ATR:g} ATR / target {TARGET_ATR:g} ATR "
            f"(R = {TARGET_ATR / STOP_ATR:g}, break-even {proj.mc['long']['breakeven'] * 100:.0f} %)"
        )
        rows = []
        for side, key, lv in (("🟢 Compra", "long", proj.mc["long_levels"]), ("🔴 Venta", "short", proj.mc["short_levels"])):
            r = proj.mc[key]
            rows.append({
                "Lado": side, "Entry": f"${proj.last_close:,.2f}", "Stop": f"${lv[0]:,.2f}", "Target": f"${lv[1]:,.2f}",
                "Target primero": _pct(r["p_target"]), "Stop primero": _pct(r["p_stop"]),
                "Ninguno": _pct(r["p_neither"]), "R promedio": f"{r['avg_R']:+.3f}", "Veredicto": r["verdict"],
            })
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
        st.caption(
            "Cada replay toma, vela por vela, una vela real de los ultimos dias del mismo horario (±2 velas) y la "
            "escala al precio actual. Si una vela toca stop y target, cuenta como stop (criterio conservador). "
            "El veredicto compara 'target primero' entre los replays que tocaron algun lado contra el break-even 1/(1+R)."
        )

    st.markdown("###### Validacion fuera de muestra (ultimo 20 % del historico, nunca visto en el ajuste)")
    v1, v2, v3, v4 = st.columns(4)
    sig = "significativo" if m["p_value"] < 0.05 else "no significativo"
    v1.metric("Acierto direccional", _pct(m["accuracy"]))
    v2.metric("p-valor binomial", f"{m['p_value']:.3f}")
    v3.metric("P(sube | dice sube)", _pct(m["p_up_given_said_up"]))
    v4.metric("Cobertura banda 90 %", _pct(m["coverage90"]))
    st.caption(
        f"Acierto: {m['hits']} de {m['n_independent']} ventanas independientes ({sig}). "
        f"Distribucion binomial: P(X ≥ {m['hits']}) con n = {m['n_independent']}, p = 0.5. Un p-valor < 0.05 indica que "
        "el acierto dificilmente es azar; si es mayor, tratar la direccion como moneda al aire y usar solo las bandas. "
        f"Bayes: P(sube | señal alcista) = {_pct(m['p_up_given_said_up'])} vs tasa base {_pct(m['base_rate_up'])}. "
        f"R² fuera de muestra {m['r2_oos']:+.3f}. Brier de la logistica: {m['brier']:.3f} (0.25 = azar). "
        f"Ridge λ = {m['lambda']:g} elegido en validacion; {proj.n_train:,} velas etiquetadas."
    )
    with st.expander("Ver pesos de las variables del modelo"):
        st.plotly_chart(coef_chart(proj), width="stretch")
        st.caption("Coeficientes estandarizados del Ridge al horizonte final: verde empuja al alza, rojo a la baja.")


@st.fragment(run_every=refresh_seconds or None)
def render_projection() -> None:
    projections: dict[str, tuple[pd.DataFrame, Projection | None]] = {}
    with st.spinner("Ajustando modelos de regresion..."):
        for label in HORIZONS:
            try:
                df = fetch_deep(label)
                if df.empty:
                    projections[label] = (df, None)
                    continue
                proj = _cached_projection(label, str(df.index[-1]), len(df), df)
                projections[label] = (df, proj)
            except Exception as exc:  # yfinance a veces devuelve datos incompletos
                st.warning(f"No se pudo calcular la proyeccion de {label} ({exc!r}).")
                projections[label] = (pd.DataFrame(), None)

    ok = {k: v for k, v in projections.items() if v[1] is not None}
    if not ok:
        st.warning("No hay suficientes velas para ajustar los modelos ahora mismo.")
        return

    last_df = ok.get("5m", next(iter(ok.values())))[0]
    render_data_status(to_new_york_time(last_df.index[-1]), current_session_label(last_df.index[-1]))

    cols = st.columns(len(HORIZONS))
    for col, label in zip(cols, HORIZONS):
        proj = projections[label][1]
        with col:
            if proj is None:
                st.metric(f"{label} · {HORIZON_TEXT[label]}", "sin datos")
                continue
            text, color_key = signal_label(proj.consensus_p_up)
            end_med = proj.reg_bands[2, -1]
            st.markdown(
                f'<div class="oro-card" style="border-left:4px solid {COLORS[color_key]};">'
                f'<span style="opacity:0.75;">{label} · {HORIZON_TEXT[label]}</span><br>'
                f'<b style="font-size:1.5rem;">{text}</b> &nbsp; P(sube) {proj.consensus_p_up * 100:.1f} %<br>'
                f'<span style="opacity:0.85;">Mediana ${end_med:,.2f} ({(end_med / proj.last_close - 1) * 100:+.2f} %) · '
                f'90 %: ${proj.reg_bands[0, -1]:,.0f}–${proj.reg_bands[4, -1]:,.0f}</span><br>'
                f'<span style="opacity:0.6;font-size:0.85rem;">Acierto historico {proj.metrics["accuracy"] * 100:.0f} % · '
                f'p-valor {proj.metrics["p_value"]:.2f}</span></div>',
                unsafe_allow_html=True,
            )

    tabs = st.tabs([f"{label} · {HORIZON_TEXT[label]}" for label in HORIZONS])
    for tab, label in zip(tabs, HORIZONS):
        df, proj = projections[label]
        with tab:
            if proj is None:
                st.info(f"No hay suficientes velas de {label} para proyectar.")
            else:
                render_detail(df, proj)


render_projection()

st.markdown("---")
st.caption(
    "Estimacion estadistica sobre el historico reciente de PAXG-USD (proxy de XAU/USD), no una promesa ni una orden. "
    "Noticias, datos macro o gaps pueden hacer cosas que el historico nunca hizo. "
    f"Monte Carlo inspirado en el 'Time Machine' de github.com/Jakeschincariol/day-trader-skill (seed {MC_SEED}, "
    f"{MC_REPLAYS:,} replays)."
)
