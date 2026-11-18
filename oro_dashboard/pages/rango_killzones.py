import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from core import config
from core.daily_levels import LOCAL_TZ, calculate_daily_levels
from core.data import fetch_ohlcv
from core.killzone_levels import (
    killzone_history,
    killzone_summary,
    killzones_for,
    range_bands,
    session_bounds,
    to_local,
    trading_sessions,
)
from core.state import render_refresh_control
from ui.theme import COLORS, get_plotly_template, inject_css

inject_css()
st.title("📐 Rango D1 y Killzones")
st.caption(
    "Precio en línea (velas M5) con el máximo y el mínimo del día anterior (PDH/PDL), las killzones de "
    "Asia, Londres y Nueva York con su zona de fin, el rango histórico del 95 % y 99 % hasta el cierre del "
    "D1 y las señales de la regla de Niveles diarios. Hora de El Salvador. Es estadística del pasado, "
    "no un pronóstico ni una recomendación."
)

refresh_seconds = render_refresh_control()

KZ_COLORS = {"Asia": COLORS["series_zone"], "Londres": COLORS["series_secondary"], "Nueva York": COLORS["series_hist"]}


@st.cache_data(ttl=3600, show_spinner=False)
def _history_1h() -> pd.DataFrame:
    return to_local(fetch_ohlcv("730d", "60m"))


@st.cache_data(ttl=900, show_spinner=False)
def _kz_history(df_local: pd.DataFrame) -> pd.DataFrame:
    return killzone_history(df_local)


def _rgba(hex_color: str, alpha: float) -> str:
    h = hex_color.lstrip("#")
    return f"rgba({int(h[0:2], 16)},{int(h[2:4], 16)},{int(h[4:6], 16)},{alpha})"


@st.fragment(run_every=refresh_seconds or None)
def render() -> None:
    raw = fetch_ohlcv("60d", "5m")
    if raw.empty:
        st.error("No se pudieron descargar velas M5.")
        return
    now = pd.Timestamp.now(tz=LOCAL_TZ)
    df = to_local(raw)
    df = df[df.index + pd.Timedelta(minutes=5) <= now]  # solo velas cerradas
    sessions = trading_sessions(df)
    days = sorted(sessions)
    if len(days) < 2:
        st.warning("No hay suficientes sesiones para calcular el rango del día anterior.")
        return

    # Sesion actual = la que contiene "ahora" (si es fin de semana, la ultima disponible)
    cur = max(d for d in days if d <= (now + pd.Timedelta(hours=8)).date())
    prev = days[days.index(cur) - 1]
    s_prev, s_cur = sessions[prev], sessions[cur]
    pdh, pdl = float(s_prev["high"].max()), float(s_prev["low"].min())
    last_t, last = s_cur.index[-1], float(s_cur["close"].iloc[-1])
    cur_start, cur_end = session_bounds(cur)
    zones = killzones_for(cur)

    # Señales de la regla de Niveles diarios (valores por defecto de esa pagina)
    levels = calculate_daily_levels(raw)
    sig = levels.data.copy()
    sig.index = sig.index.tz_convert(LOCAL_TZ)

    # Rango historico hasta el fin de cada killzone y el cierre del D1
    targets = [z.end for z in zones if z.end > now] + [cur_end]
    bands = range_bands(_history_1h(), now, last, sorted(set(targets)))

    c = st.columns(5)
    c[0].metric("PDH (máximo de ayer)", f"{pdh:,.2f}")
    c[1].metric("PDL (mínimo de ayer)", f"{pdl:,.2f}")
    c[2].metric("Último precio", f"{last:,.2f}", f"vela de {last_t:%H:%M}", delta_color="off")
    pos = "dentro del rango" if pdl <= last <= pdh else ("bajo el PDL" if last < pdl else "sobre el PDH")
    c[3].metric("Distancia al PDL", f"{last - pdl:+,.2f}", pos, delta_color="off")
    c[4].metric("Sesgo Niveles diarios", levels.bias)

    # ---------------- grafico ----------------
    view = df[(df.index >= session_bounds(prev)[0]) & (df.index < cur_end)]
    fig = go.Figure()
    y_all = list(view["close"]) + [pdh, pdl]
    if len(bands):
        y_all += list(bands["lo99"]) + list(bands["hi99"])
    y_lo, y_hi = min(y_all), max(y_all)
    pad = (y_hi - y_lo) * 0.04

    for z in killzones_for(prev) + zones:
        color = KZ_COLORS[z.name]
        fig.add_vrect(x0=z.start, x1=z.end, fillcolor=_rgba(color, 0.10), line_width=0, layer="below")
        fig.add_annotation(x=z.start + (z.end - z.start) / 2, y=y_hi + pad, text=f"KZ {z.name}",
                           showarrow=False, font={"size": 11, "color": color}, yanchor="bottom")
        k = view[(view.index >= z.start) & (view.index < z.end)]
        if k.empty:
            # killzone por venir: solo marcar su fin
            fig.add_vline(x=z.end, line={"color": color, "width": 1.5, "dash": "dot"})
            continue
        # zona de fin: rango maximo/minimo de la killzone proyectado hasta el cierre del D1
        kz_end_proj = min(session_bounds((z.end + pd.Timedelta(hours=8)).date())[1], cur_end)
        hi, lo, close = float(k["high"].max()), float(k["low"].min()), float(k["close"].iloc[-1])
        if now >= z.end:
            fig.add_shape(type="rect", x0=z.end, x1=kz_end_proj, y0=lo, y1=hi,
                          fillcolor=_rgba(color, 0.06), line={"color": _rgba(color, 0.6), "width": 1, "dash": "dot"},
                          layer="below")
            fig.add_vline(x=z.end, line={"color": color, "width": 1.5})
            fig.add_trace(go.Scatter(x=[k.index[-1]], y=[close], mode="markers",
                                     marker={"symbol": "square", "size": 9, "color": color,
                                             "line": {"color": COLORS["bg_page"], "width": 1.5}},
                                     name=f"Fin KZ {z.name}", showlegend=False,
                                     hovertemplate=f"Fin KZ {z.name} {z.end:%H:%M}<br>Cierre %{{y:,.2f}}<br>"
                                                   f"Máx {hi:,.2f} · Mín {lo:,.2f}<extra></extra>"))
        else:
            fig.add_vline(x=z.end, line={"color": color, "width": 1.5, "dash": "dot"})

    if len(bands):
        x = [last_t] + list(bands["hasta"])
        for lo_c, hi_c, alpha, name in (("lo99", "hi99", 0.10, "Rango 99 %"), ("lo95", "hi95", 0.20, "Rango 95 %")):
            fig.add_trace(go.Scatter(x=x + x[::-1], y=[last] + list(bands[hi_c]) + list(bands[lo_c])[::-1] + [last],
                                     fill="toself", fillcolor=_rgba(COLORS["series_hist"], alpha),
                                     line={"color": _rgba(COLORS["series_hist"], 0.5), "width": 1},
                                     name=name, hoverinfo="skip"))

    for v, n in ((pdh, "PDH"), (pdl, "PDL")):
        fig.add_hline(y=v, line={"color": COLORS["text_secondary"], "width": 1.2, "dash": "dash"},
                      annotation_text=f"{n} {v:,.2f}", annotation_position="top left",
                      annotation_font_color=COLORS["text_secondary"])
    if levels.active_levels:
        up = max(levels.active_levels["H07"], levels.active_levels["H1130"])
        lv_start = pd.Timestamp(now.date(), tz=LOCAL_TZ)
        for v, n, color in ((up, "Gatillo compra", COLORS["bull"]), (levels.active_levels["L16"], "Gatillo venta", COLORS["bear"])):
            fig.add_shape(type="line", x0=lv_start, x1=cur_end, y0=v, y1=v, line={"color": color, "width": 1.5})
            fig.add_annotation(x=lv_start, y=v, text=f"{n} {v:,.2f}", showarrow=False, xanchor="left",
                               yanchor="bottom", font={"color": color, "size": 11})

    fig.add_trace(go.Scatter(x=view.index, y=view["close"], mode="lines", name=config.SYMBOL_LABEL,
                             line={"color": COLORS["warning"], "width": 2},
                             hovertemplate="%{x|%d %b %H:%M}<br>%{y:,.2f}<extra></extra>"))
    sv = sig[sig.index >= view.index[0]]
    for col, name, symbol, color in (("bull_signal", "Señal compra", "triangle-up", COLORS["bull"]),
                                     ("bear_signal", "Señal venta", "triangle-down", COLORS["bear"])):
        pts = sv[sv[col]]
        fig.add_trace(go.Scatter(x=pts.index, y=pts["close"], mode="markers+text", name=name,
                                 text=[f"{name.split()[1].upper()} {t:%H:%M}" for t in pts.index],
                                 textposition="bottom center" if col == "bull_signal" else "top center",
                                 textfont={"color": color, "size": 11},
                                 marker={"symbol": symbol, "size": 13, "color": color,
                                         "line": {"color": COLORS["bg_page"], "width": 1.5}},
                                 hovertemplate=f"{name}<br>%{{x|%d %b %H:%M}} · %{{y:,.2f}}<extra></extra>"))
    fig.update_layout(template=get_plotly_template(), height=640, hovermode="x unified",
                      legend={"orientation": "h", "y": -0.12}, margin={"t": 40, "r": 20},
                      yaxis={"range": [y_lo - pad, y_hi + pad * 3], "title": "Precio"},
                      xaxis={"range": [view.index[0], cur_end], "title": "Hora de El Salvador"})
    st.plotly_chart(fig, width="stretch")
    st.caption(
        "Zonas sombreadas: killzones. Línea vertical continua y cuadro: fin de la killzone, con su máximo y "
        "mínimo proyectados hasta el cierre del D1. Línea punteada: fin de una killzone que aún no termina. "
        "Abanico azul: rango donde quedó el precio el 95 % y el 99 % de las sesiones pasadas. Es un rango, no una dirección."
    )

    # ---------------- tablas ----------------
    left, right = st.columns(2)
    with left:
        st.markdown("#### Killzones de hoy")
        summ = killzone_summary(s_cur, zones, pdh, pdl, now)
        st.dataframe(summ, hide_index=True, width="stretch",
                     column_config={c_: st.column_config.NumberColumn(format="%.2f") for c_ in ("Máximo", "Mínimo", "Cierre")})
        st.markdown("#### Rango desde ahora")
        if len(bands):
            st.dataframe(pd.DataFrame({
                "Hasta": bands["hasta"].dt.strftime("%H:%M"),
                "95 %": [f"{a:,.2f} – {b:,.2f}" for a, b in zip(bands["lo95"], bands["hi95"])],
                "99 %": [f"{a:,.2f} – {b:,.2f}" for a, b in zip(bands["lo99"], bands["hi99"])],
                "Sesiones": bands["n"],
            }), hide_index=True, width="stretch")
        else:
            st.caption("No hay suficientes sesiones de 1 h para calcular el rango.")
    with right:
        st.markdown("#### Qué hizo cada killzone con el PDH y el PDL")
        h = _kz_history(df)
        if len(h):
            t = h.groupby("kz").agg(Sesiones=("dia", "count"), **{
                "Barrió PDH": ("barre_pdh", "sum"), "…y cerró debajo": ("vuelve_pdh", "sum"),
                "Barrió PDL": ("barre_pdl", "sum"), "…y cerró arriba": ("vuelve_pdl", "sum")})
            st.dataframe(t.reindex([z.name for z in zones]).dropna(how="all"), width="stretch")
        st.markdown("#### Señales de Niveles diarios en 60 días")
        allsig = sig[sig["bull_signal"] | sig["bear_signal"]]
        rows = []
        for ts, r in allsig.iterrows():
            i = sig.index.get_loc(ts)
            if i + 36 < len(sig):
                side = 1 if r["bull_signal"] else -1
                rows.append({"side": side, "r1": (sig["close"].iloc[i + 12] - r["close"]) * side,
                             "r3": (sig["close"].iloc[i + 36] - r["close"]) * side})
        if rows:
            r = pd.DataFrame(rows)
            st.dataframe(pd.DataFrame([{
                "Señal": n, "Veces": int((r.side == s).sum()),
                "A favor tras 1 h": f"{int((r[r.side == s].r1 > 0).sum())} de {int((r.side == s).sum())}",
                "A favor tras 3 h": f"{int((r[r.side == s].r3 > 0).sum())} de {int((r.side == s).sum())}",
            } for s, n in ((1, "Compra"), (-1, "Venta"))]), hide_index=True, width="stretch")
        st.caption("Con pocas señales, estos conteos no dicen si la regla funciona.")

    st.caption(f"Datos de Yahoo Finance ({config.SYMBOL}), con retraso. Actualizado a las {now:%H:%M:%S} "
               "hora de El Salvador. Esta página no abre operaciones ni envía órdenes.")


render()
