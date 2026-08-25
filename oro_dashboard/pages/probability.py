import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import matplotlib.pyplot as plt
import streamlit as st

from core import config
from core.calendar import IMPACTO_COLOR, events_naive
from core.data import fetch_deep, fetch_interval
from core.probability import backtest_by_trend, backtest_targets, backtest_targets_intrabar, direction_levels
from core.smc_zones import atr, detect_liquidity_sweeps, detect_order_blocks, label_structure, zone_probability
from core.structure_naive import nearest_liquidity_target, own_trend
from core.timeutil import current_session_label, to_new_york_time
from core.state import render_refresh_control
from ui.charts import add_calendar_events, add_level_lines, add_update_marker, candlestick_chart, grouped_bar_chart
from ui.insight_cards import mini_bar_chart, render_insight_card
from ui.mpl_charts import structure_multi_timeframe_chart, structure_smc_chart, targets_price_chart
from ui.theme import COLORS, inject_css, render_data_status

inject_css()

st.title("🎯 Probabilidad de Targets")
st.caption(
    "Backtest historico (Entry ±1%/±2% SL-TP) sobre ventanas de 30 velas: probabilidad global, "
    "cruzada con el calendario economico en la vista diaria, y condicional por regimen de tendencia."
)

refresh_seconds = render_refresh_control()

top1, top2 = st.columns([1, 1.4])
direction_label = top1.radio("Direccion", ["Compra", "Venta"], horizontal=True, key="prob_direction")
direction = "compra" if direction_label == "Compra" else "venta"
horizon_label = top2.radio(
    "Horizonte", ["Intradia (5m, 30 dias)", "Diario (1D, 2 años) + Calendario"], horizontal=True, key="prob_horizon"
)
is_daily = horizon_label.startswith("Diario")


@st.fragment(run_every=refresh_seconds or None)
def render_global() -> None:
    interval = "1d" if is_daily else "5m"
    df = fetch_interval(interval)
    if df.empty or len(df) < 60:
        st.warning("No hay suficientes velas para calcular probabilidad en este horizonte.")
        return

    close = df["close"].to_numpy(dtype=float)
    high = df["high"].to_numpy(dtype=float)
    low = df["low"].to_numpy(dtype=float)
    result = backtest_targets(close, direction=direction)

    render_data_status(to_new_york_time(df.index[-1]), current_session_label(df.index[-1]))

    entry = float(close[-1])
    if direction == "compra":
        stoploss, target1, target2 = entry * 0.99, entry * 1.01, entry * 1.02
    else:
        stoploss, target1, target2 = entry * 1.01, entry * 0.99, entry * 0.98

    st.metric("Entry", f"${entry:,.2f}")
    st.caption(f"Muestra: {result['sample_size']} ventanas de 30 velas ({interval}).")

    regime_summary = backtest_by_trend(close, direction=direction)
    intrabar = backtest_targets_intrabar(high, low, close, direction=direction)
    n = result["sample_size"]

    card1, card2, card3 = st.columns(3)
    with card1:
        regime_colors = [COLORS["bull"], COLORS["bear"], COLORS["text_muted"]]
        fig1 = mini_bar_chart(list(regime_summary["Regimen"]), list(regime_summary["Target1 (%)"]), regime_colors)
        render_insight_card(
            icon="🎯", label="Target 1 alcanzado", value=f"{result['target1_pct']:.1f}%",
            subtitle=f"Muestra: {n} ventanas ({interval})", accent=COLORS["bull"],
            hidden_html=(
                "Este promedio mezcla <b>3 regimenes distintos</b> (alcista, bajista, lateral). "
                "La probabilidad real depende de cual este vigente ahora, no de un solo numero global."
            ),
            fig=fig1,
        )
    with card2:
        independent_n = max(1, n // 30)
        fig2 = mini_bar_chart(
            ["Ventanas contadas", "Obs. independientes"], [n, independent_n],
            [COLORS["series_hist"], COLORS["warning"]], value_fmt="{:.0f}",
        )
        render_insight_card(
            icon="🎯", label="Target 2 alcanzado", value=f"{result['target2_pct']:.1f}%",
            subtitle=f"Muestra: {n} ventanas ({interval})", accent=COLORS["series_forecast"],
            hidden_html=(
                f"Las {n} ventanas se <b>solapan entre si</b> (comparten hasta 29 de 30 velas). "
                f"La evidencia realmente independiente es mucho menor: <b>~{independent_n}</b> observaciones, no {n}."
            ),
            fig=fig2,
        )
    with card3:
        delta = intrabar["stoploss_pct"] - result["stoploss_pct"]
        fig3 = mini_bar_chart(
            ["Solo cierre", "Con mechas (H/L)"], [result["stoploss_pct"], intrabar["stoploss_pct"]],
            [COLORS["text_muted"], COLORS["bear"]],
        )
        render_insight_card(
            icon="🛑", label="Stoploss tocado", value=f"{result['stoploss_pct']:.1f}%",
            subtitle="Calculado solo con cierres (Close)", accent=COLORS["bear"],
            hidden_html=(
                f"Este {result['stoploss_pct']:.1f}% solo cuenta <b>cierres</b> mas alla del stop. Contando las "
                f"<b>mechas</b> (High/Low), el stop se toca el {intrabar['stoploss_pct']:.1f}% de las veces "
                f"({delta:+.1f} puntos mas real)."
            ),
            fig=fig3,
        )

    if is_daily:
        reciente = df.tail(25)
        fig = candlestick_chart(reciente, title=f"{config.SYMBOL_LABEL} — Probabilidad de Targets (1D) + Calendario Economico")
        events = events_naive()
        if not events.empty:
            eventos_semana = events[events["Fechas"] >= reciente.index.min()]
            add_calendar_events(fig, eventos_semana, IMPACTO_COLOR)
            st.caption(
                f"Eventos economicos relevantes para {config.SYMBOL_LABEL} en la ventana mostrada: {len(eventos_semana)}."
            )
        else:
            st.info("No se encontro el calendario economico (calendario_economico_ftmo/economic_calendar.xlsx).")
    else:
        fig = candlestick_chart(df, title=f"{config.SYMBOL_LABEL} (5m) — Probabilidad de Targets")

    add_level_lines(fig, entry=entry, stoploss=stoploss, target1=target1, target2=target2)
    add_update_marker(fig, to_new_york_time(df.index[-1]))
    st.plotly_chart(fig, width="stretch")


render_global()

st.markdown("---")
st.markdown("##### 📊 Probabilidad condicional por tipo de patron (15m)")
st.caption(
    "Clasifica cada ventana de 30 velas por pendiente (Alcista / Bajista / Lateral) y mide la "
    f"probabilidad de {direction_label.lower()} dentro de cada regimen."
)


@st.fragment(run_every=refresh_seconds or None)
def render_conditional() -> None:
    df = fetch_interval("15m")
    if df.empty or len(df) < 60:
        st.warning("No hay suficientes velas de 15m para el analisis condicional.")
        return

    close = df["close"].to_numpy(dtype=float)
    summary = backtest_by_trend(close, direction=direction)

    fig = grouped_bar_chart(
        summary["Regimen"],
        {
            "Target 1": summary["Target1 (%)"],
            "Target 2": summary["Target2 (%)"],
            "Stoploss": summary["Stoploss (%)"],
        },
        colors={"Target 1": COLORS["bull"], "Target 2": COLORS["series_forecast"], "Stoploss": COLORS["bear"]},
        title=f"Probabilidad condicional por regimen — {direction_label} (15m)",
    )
    st.plotly_chart(fig, width="stretch")
    st.dataframe(summary, width="stretch", hide_index=True)

    st.markdown("###### Precio, Entry, Stoploss y Targets (compra y venta)")
    entry_now = float(close[-1])
    updated_label = f"{to_new_york_time(df.index[-1]).strftime('%d/%m/%Y %H:%M')} (NY)"

    for dir_key, dir_label, badge in (("compra", "COMPRA", "🟢"), ("venta", "VENTA", "🔴")):
        sl, t1, t2 = direction_levels(entry_now, 0.01, 0.01, 0.02, dir_key)
        st.markdown(f"**{badge} {dir_label}**")
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Entry", f"${entry_now:,.2f}")
        m2.metric("Stoploss", f"${sl:,.2f}")
        m3.metric("Target 1", f"${t1:,.2f}")
        m4.metric("Target 2", f"${t2:,.2f}")
        fig_mpl = targets_price_chart(
            df, entry=entry_now, stoploss=sl, target1=t1, target2=t2,
            updated_at_label=updated_label, symbol_label=config.SYMBOL_LABEL,
            direction_label=dir_label, entry_label="Entry" if dir_key == "compra" else "Entry (venta)",
        )
        st.pyplot(fig_mpl, width="stretch")
        plt.close(fig_mpl)


render_conditional()

st.markdown("---")
st.markdown(f"##### 📐 Estructura SMC ({config.ICT_STRUCTURE_INTERVAL}) — Order Blocks y Barridas de Liquidez")
st.caption(
    f"Order Blocks y barridas de liquidez de la Estrategia Institucional (SMC) en {config.ICT_STRUCTURE_INTERVAL}, "
    f"con el sesgo diario ({config.ICT_BIAS_INTERVAL}) vigente en el titulo. Cada zona se etiqueta con su "
    "probabilidad de continuacion, estimada contra estructuras analogas de todo el historico disponible "
    "(no solo las mas recientes)."
)


@st.fragment(run_every=refresh_seconds or None)
def render_structure_smc() -> None:
    df_bias = fetch_interval(config.ICT_BIAS_INTERVAL)
    df_structure = fetch_deep(config.ICT_STRUCTURE_INTERVAL)
    if df_bias.empty or df_structure.empty or len(df_structure) < 60:
        st.warning(f"No hay suficientes velas en {config.ICT_BIAS_INTERVAL}/{config.ICT_STRUCTURE_INTERVAL} ahora mismo.")
        return

    macro_bias = label_structure(df_bias)["bias"]
    zones = detect_order_blocks(df_structure, lookback=5, max_zones=200)
    sweeps = detect_liquidity_sweeps(df_structure, lookback=5, max_sweeps=50)
    atr_value = float(atr(df_structure).iloc[-1])
    for zone in zones:
        zone["prob"] = zone_probability(zones, zone, atr_value)

    fig_smc = structure_smc_chart(
        df_structure, zones, sweeps,
        symbol_label=config.SYMBOL_LABEL, structure_interval_label=config.ICT_STRUCTURE_INTERVAL,
        macro_bias=macro_bias,
    )
    st.pyplot(fig_smc, width="stretch")
    plt.close(fig_smc)
    st.caption(
        f"Historico analizado: {len(df_structure)} velas de {config.ICT_STRUCTURE_INTERVAL} "
        f"({df_structure.index[0].strftime('%d/%m/%Y')} → {df_structure.index[-1].strftime('%d/%m/%Y')}) "
        f"— {sum(1 for z in zones if z['status'] in ('continuo', 'fallo'))} estructuras resueltas usadas como analogos."
    )


render_structure_smc()

st.markdown("---")
st.markdown("##### 🧭 Estructura Multi-Temporalidad (5m / 15m / 1h)")
st.caption(
    "Misma confluencia 1h/15m/5m de la Estrategia Institucional (SMC): tendencia vigente, "
    "swings y niveles de Entrada/SL/TP de cada temporalidad, en un solo vistazo."
)


@st.fragment(run_every=refresh_seconds or None)
def render_structure_mtf() -> None:
    panels = []
    tendencias: dict[str, str | None] = {}
    choch_recientes: list[tuple[str, dict]] = []
    for label in ("1h", "15m", "5m"):
        df_tf = fetch_interval(label)
        if df_tf.empty or len(df_tf) < 60:
            continue
        swings, tendencia, quiebres = own_trend(df_tf)
        tendencias[label] = tendencia
        if quiebres and quiebres[-1]["tipo"] == "CHoCH":
            choch_recientes.append((label, quiebres[-1]))

        entry = sl = tp = kind = None
        if tendencia is not None:
            entry = float(df_tf["close"].iloc[-1])
            tp = nearest_liquidity_target(swings, tendencia, entry)
            sl = float(df_tf["low"].tail(20).min()) if tendencia == "alcista" else float(df_tf["high"].tail(20).max())
            kind = "bullish" if tendencia == "alcista" else "bearish"

        panel_df = swings.tail(150)
        breaks = [
            {"time": swings.index[q["idx"]], "level": q["level"], "kind": q["kind"], "tipo": q["tipo"]}
            for q in quiebres if q["idx"] >= len(swings) - 150
        ]
        panels.append({
            "label": label, "df": panel_df, "kind": kind, "entry": entry, "sl": sl, "tp": tp, "breaks": breaks,
        })

    if not panels:
        st.warning("No hay suficientes velas en 1h/15m/5m para la estructura multi-temporalidad ahora mismo.")
        return

    # Mayoria (2/3), no unanimidad (3/3): exigir que las 3 temporalidades coincidan
    # a la vez casi nunca ocurre en la practica, asi que el veredicto quedaba "SIN
    # CONFIRMACION" de forma casi permanente — igual criterio de 2-de-3 que ya usa
    # `multi_timeframe_probability`/`multi_timeframe_bias` en core/smc_zones.py.
    alcistas = [tf for tf, t in tendencias.items() if t == "alcista"]
    bajistas = [tf for tf, t in tendencias.items() if t == "bajista"]
    if len(alcistas) >= 2:
        veredicto, alineadas, divergentes = "alcista", len(alcistas), [tf for tf in tendencias if tf not in alcistas]
    elif len(bajistas) >= 2:
        veredicto, alineadas, divergentes = "bajista", len(bajistas), [tf for tf in tendencias if tf not in bajistas]
    else:
        veredicto, alineadas, divergentes = None, 0, []

    if choch_recientes:
        detalle = ", ".join(
            f"{tf} (CHoCH {q['kind']} en ${q['level']:,.2f})" for tf, q in choch_recientes
        )
        st.info(
            f"🔄 Cambio de estructura reciente sin BOS de continuacion todavia: {detalle}. "
            "Posible entrada temprana en la nueva direccion, pero sin la confirmacion de "
            "manipulacion (AMD) ni retest que exige la Estrategia Institucional — usar con cautela."
        )

    fig_mtf = structure_multi_timeframe_chart(
        panels, symbol_label=config.SYMBOL_LABEL, veredicto=veredicto, alineadas=alineadas, divergentes=divergentes,
    )
    st.pyplot(fig_mtf, width="stretch")
    plt.close(fig_mtf)


render_structure_mtf()
