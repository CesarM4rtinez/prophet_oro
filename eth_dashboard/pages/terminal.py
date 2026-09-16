import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import streamlit as st

from core import config
from core.auto_engine import RULES, evaluate_rule
from core.backtest_engine import vectorized_scalping_score
from core.capital_client import CapitalError, get_client
from core.data_yfinance import fetch_dxy
from core.risk import suggested_size
from core.scalping import compute_indicators, score_last
from core.smc_zones import (
    build_zone_signal,
    current_session_label,
    detect_dxy_divergence,
    historical_qualified_setups,
    in_high_liquidity_session,
    multi_timeframe_bias,
    multi_timeframe_probability,
    to_new_york_time,
    zone_stats,
)
from ui.charts import (
    add_auto_engine_reference_levels,
    add_historical_setup_markers,
    add_scalping_signal_markers,
    add_update_marker,
    candlestick_chart,
)
from ui.theme import COLORS, inject_css, render_data_status

inject_css()


def _order_error_message(exc: Exception) -> str:
    text = str(exc)
    if any(term in text.lower() for term in ("stoploss", "minvalue", "profit")):
        return (
            f"{text}\n\n💡 Capital.com exige una distancia minima de SL/TP para este instrumento. "
            "Prueba a aumentar el porcentaje de Stoploss/Take Profit e intenta de nuevo."
        )
    return f"No se pudo enviar la orden: {text}"


def _market_status_label(status: str) -> tuple[str, str]:
    return config.CAPITAL_MARKET_STATUS_LABELS.get(status, ("❓", status or "Desconocido"))


# -- Helpers cacheados para el Reporte Ejecutivo (y reutilizados por el panel de
# probabilidad existente) — mismo patron que `_preview_candles`/`_browse_markets`:
# `_client` con guion bajo se excluye del hash, `environment` va explicito para no
# mezclar cache entre DEMO/LIVE. -----------------------------------------------


@st.cache_data(ttl=60, show_spinner=False)
def _mtf_probability_cached(_client, environment: str, epic: str) -> dict:
    df_1h = _client.get_candles(epic, resolution="HOUR", max_points=500)
    df_15m = _client.get_candles(epic, resolution="MINUTE_15", max_points=500)
    df_5m = _client.get_candles(epic, resolution="MINUTE_5", max_points=500)
    return multi_timeframe_probability(df_1h, df_15m, df_5m)


@st.cache_data(ttl=90, show_spinner=False)
def _institutional_bias_cached(_client, environment: str, epic: str) -> dict:
    df_day = _client.get_candles(epic, resolution="DAY", max_points=120)
    df_hour = _client.get_candles(epic, resolution="HOUR", max_points=120)
    df_m15 = _client.get_candles(epic, resolution="MINUTE_15", max_points=120)
    return multi_timeframe_bias(df_day, df_hour, df_m15)


@st.cache_data(ttl=30, show_spinner=False)
def _scalping_snapshot_cached(_client, environment: str, epic: str) -> dict | None:
    df = _client.get_candles(epic, resolution=config.DEFAULT_CAPITAL_RESOLUTION, max_points=120)
    if df.empty or len(df) < 60:
        return None
    return score_last(compute_indicators(df))


@st.cache_data(ttl=30, show_spinner=False)
def _epic_market_status_cached(_client, environment: str, epic: str) -> str | None:
    try:
        results = _client.search_markets(epic, limit=5)
    except Exception:
        return None
    match = next((m for m in results if m.get("epic") == epic), None)
    return match.get("marketStatus") if match else None


def _probability_tier(avg_probability: float) -> str:
    if avg_probability >= 70:
        return "Excelente"
    if avg_probability >= 60:
        return "Buena"
    if avg_probability >= 50:
        return "Aceptable"
    return "Neutral"


def _render_signal_detail(mtf_prob: dict, name: str) -> None:
    """Entry/SL/TP1-TP5 de la zona activa si hay confluencia favorable — usado por
    el panel de Probabilidad y por la Vista del Analista del Reporte Ejecutivo."""
    favorable = (
        mtf_prob["aligned"]
        and mtf_prob["avg_probability"] is not None
        and mtf_prob["avg_probability"] >= config.PROBABILITY_SIGNAL_MIN_AVG
    )
    if not favorable:
        st.caption("Sin confluencia favorable ahora mismo (temporalidades sin alinear o probabilidad promedio baja).")
        return
    signal = build_zone_signal(mtf_prob)
    if signal is None:
        st.caption(
            "Confluencia favorable, pero la zona activa no tiene un objetivo de liquidez valido para "
            "armar niveles de entrada ahora mismo."
        )
        return
    badge_class = "eth-badge-buy" if signal["direction"] == "BUY" else "eth-badge-sell"
    st.markdown(
        f'<div style="margin-top:0.5rem;">'
        f'<span class="eth-badge {badge_class}">{signal["direction"]}</span> '
        f'<b>{name}</b> · Entry <b>{signal["entry"]:,.2f}</b> '
        f'<span style="color:{COLORS["text_muted"]};">({signal["timeframe"]})</span>'
        f"</div>",
        unsafe_allow_html=True,
    )
    tp_cols = st.columns(5)
    for i, (col, tp) in enumerate(zip(tp_cols, signal["tps"]), start=1):
        col.metric(f"TP{i}", f"{tp:,.2f}")
    rr_text = f" · Riesgo/Beneficio a TP5 = 1:{signal['rr']:.2f}" if signal["rr"] else ""
    st.markdown(f"**SL:** {signal['sl']:,.2f}{rr_text}")
    st.caption(
        "Entry = precio actual en la temporalidad mas inmediata con datos; SL = borde opuesto de la "
        "zona activa + colchon ATR; TP1-TP5 = fracciones del objetivo de liquidez opuesto ya usado "
        "por el motor SMC institucional (TP5 = objetivo completo). Verifica los niveles en tu "
        "plataforma antes de operar — no es una orden enviada automaticamente."
    )


def _render_ceo_view(mtf_prob: dict, institutional: dict, market_status: str | None, epic_positions: list, session_label: str) -> None:
    c1, c2, c3 = st.columns(3)
    c4, c5, c6 = st.columns(3)

    if mtf_prob["avg_probability"] is not None:
        tier = _probability_tier(mtf_prob["avg_probability"])
        align_delta = "✅ Alineadas" if mtf_prob["aligned"] else "⚠️ Sin alinear"
        c1.metric("Probabilidad promedio (5m/15m/1h)", f"{mtf_prob['avg_probability']:.0f}% · {tier}", align_delta, delta_color="off")
    else:
        c1.metric("Probabilidad promedio (5m/15m/1h)", "Sin datos")

    favorable = (
        mtf_prob["aligned"]
        and mtf_prob["avg_probability"] is not None
        and mtf_prob["avg_probability"] >= config.PROBABILITY_SIGNAL_MIN_AVG
    )
    signal = build_zone_signal(mtf_prob) if favorable else None
    if signal:
        rr_delta = f"RR 1:{signal['rr']:.2f} a TP5 ({signal['timeframe']})" if signal["rr"] else signal["timeframe"]
        c2.metric("Señal activa", f"{signal['direction']} @ {signal['entry']:,.2f}", rr_delta, delta_color="off")
    else:
        c2.metric("Señal activa", "Sin señal clara ahora")

    status_icon, status_label = _market_status_label(market_status or "")
    c3.metric("Sesion y mercado", session_label, f"{status_icon} {status_label}", delta_color="off")

    armed = st.session_state["capital_armed"]
    trades_today = st.session_state.get("capital_trades_this_session", 0)
    max_trades = st.session_state.get("capital_max_trades", config.DEFAULT_MAX_AUTO_TRADES_PER_SESSION)
    rule_short = "Scalping" if st.session_state.get("capital_rule") == RULES[0] else "SMC Institucional"
    c4.metric("Motor semi-automatico", "Armado" if armed else "Desarmado", f"{trades_today}/{max_trades} hoy · {rule_short}", delta_color="off")

    if epic_positions:
        total_pl = sum(p.profit_loss for p in epic_positions)
        currency = epic_positions[0].currency
        c5.metric("P&L abierto (este activo)", f"{total_pl:+,.2f} {currency}", total_pl)
    else:
        c5.metric("P&L abierto (este activo)", "Sin posiciones")

    macro_bias = institutional["macro_bias"].capitalize()
    mss = institutional["macro_mss"]
    mss_delta = f"MSS confirmado ({mss['kind']})" if mss else "Sin MSS reciente"
    c6.metric("Sesgo institucional (SMC)", macro_bias, mss_delta, delta_color="off")


def _render_analyst_view(mtf_prob: dict, institutional: dict, scalping: dict | None, name: str) -> None:
    st.markdown("##### 📐 Probabilidad por temporalidad")
    rows = []
    for label in ("1h", "15m", "5m"):
        entry = mtf_prob["per_timeframe"].get(label)
        if entry and entry["prob"]:
            p = entry["prob"]
            rows.append(
                {
                    "Temporalidad": label, "Sesgo": entry["kind"], "Probabilidad %": round(p["probability"], 1),
                    "Tier": p["tier"], "Fuegos": p["fires"], "Analogos (n)": p["sample_size"],
                    "Continuacion analogos %": round(p["analog_continuation_pct"], 1),
                    "Exito estructura reciente %": round(p["recent_structure_success_pct"], 1),
                    "Retest %": round(p["retest_pct"], 1),
                    "Aviso retest bajo": "⚠️" if p["low_retest_warning"] else "",
                }
            )
        else:
            rows.append(
                {
                    "Temporalidad": label, "Sesgo": "—", "Probabilidad %": None, "Tier": "Sin datos", "Fuegos": None,
                    "Analogos (n)": None, "Continuacion analogos %": None, "Exito estructura reciente %": None,
                    "Retest %": None, "Aviso retest bajo": "",
                }
            )
    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)

    st.markdown("##### 🎯 Señal completa (Entry/SL/TP1-TP5)")
    _render_signal_detail(mtf_prob, name)

    st.markdown("##### 🏛️ Estructura institucional (SMC)")
    ic1, ic2, ic3, ic4 = st.columns(4)
    ic1.metric("Sesgo macro (1d)", institutional["macro_bias"].capitalize())
    mss = institutional["macro_mss"]
    ic2.metric("MSS", f"{mss['kind']} @ {mss['level']:,.2f}" if mss else "Sin MSS reciente")
    stats = zone_stats(institutional["structure_zones"])
    ic3.metric("Order blocks (1h)", stats["total"], f"{stats['continuo_pct']:.0f}% continuo", delta_color="off")
    ic4.metric("FVG / Barridas (M15)", f"{len(institutional['entry_fvgs'])} / {len(institutional['entry_sweeps'])}")

    setups = institutional["high_probability_setups"]
    if setups:
        st.caption(f"{len(setups)} entrada(s) de alta probabilidad (AMD confirmado, RR >= {config.ICT_MIN_RR:g}):")
        st.dataframe(
            pd.DataFrame([{"Direccion": s["direccion"], "Motivo": s["motivo"], "RR": round(s["rr"], 2)} for s in setups]),
            width="stretch", hide_index=True,
        )
    else:
        st.caption("Sin entradas institucionales de alta probabilidad confirmadas ahora mismo.")

    st.markdown("##### ⚡ Scorecard de scalping (M15)")
    if scalping is None:
        st.caption("No hay suficientes velas M15 para calcular el scorecard.")
    else:
        sc1, sc2, sc3 = st.columns(3)
        sc1.metric("Score", f"{scalping['score']:+.2f}")
        sc2.metric("Prob. compra / venta", f"{scalping['buy_probability']:.0f}% / {scalping['sell_probability']:.0f}%")
        sc3.metric("Volumen relativo", f"{scalping['rel_volume']:.2f}x")
        comp_df = pd.DataFrame([{"Indicador": k, "Valor": round(v, 3)} for k, v in scalping["components"].items()])
        st.dataframe(comp_df, width="stretch", hide_index=True)

    st.caption(
        "Metodologia publica (order blocks, FVG, barridas de liquidez, scorecard tecnico multi-indicador) — "
        "no replica ningun algoritmo propietario ni garantiza resultados. Verifica siempre en la plataforma "
        "antes de operar."
    )


st.title("💹 Terminal de Trading — Capital.com")
st.caption(
    "Conecta tu cuenta de Capital.com, elige el entorno y la cuenta, busca un instrumento y opera de forma "
    "manual o mediante el motor semi-automatico. El login nunca ocurre solo: siempre lo dispara el boton Conectar."
)

creds = config.get_capital_credentials()

st.session_state.setdefault("capital_environment", creds.default_environment if creds.default_environment in ("DEMO", "LIVE") else "DEMO")
st.session_state.setdefault("capital_account_name", creds.default_account_name)
st.session_state.setdefault("capital_connected", False)
st.session_state.setdefault("capital_armed", False)
st.session_state.setdefault("capital_trades_this_session", 0)
st.session_state.setdefault("capital_automation_log", [])
st.session_state.setdefault("capital_last_evaluated_bar", None)
st.session_state.setdefault("capital_auto_opened_deals", set())
st.session_state.setdefault("capital_breakeven_done", set())
st.session_state.setdefault("capital_last_auto_trade_date", None)
st.session_state.setdefault("capital_news_pause", False)
st.session_state.setdefault("capital_session_gate", True)

# -- Sidebar: conexion ---------------------------------------------------------------

st.sidebar.markdown("### 🔐 Conexion Capital.com")

if not config.capital_credentials_present():
    st.sidebar.error("Faltan credenciales en eth_dashboard/.env (CAPITAL_API_KEY / CAPITAL_API_USER / CAPITAL_API_PASSWORD).")

environment = st.sidebar.selectbox("Entorno", options=["DEMO", "LIVE"], key="capital_environment")
account_name_input = st.sidebar.text_input("Nombre de cuenta", key="capital_account_name")

if environment == "LIVE":
    st.sidebar.markdown('<span class="eth-badge eth-badge-live">⚠️ CUENTA REAL — dinero real</span>', unsafe_allow_html=True)
else:
    st.sidebar.markdown('<span class="eth-badge eth-badge-demo">🧪 DEMO — sin riesgo</span>', unsafe_allow_html=True)

connect_clicked = st.sidebar.button("🔌 Conectar", width="stretch", disabled=not config.capital_credentials_present())

if connect_clicked:
    try:
        client = get_client(environment, creds.api_key, creds.identifier, creds.password)
        if not client.is_connected:
            client.login()
        account = client.get_account_by_name(account_name_input)
        if account is None:
            st.sidebar.warning(f"No se encontro una cuenta llamada '{account_name_input}' en {environment}. Se usa la cuenta activa por defecto.")
        else:
            client.switch_account(account.account_id)
        st.session_state["capital_connected"] = True
        st.sidebar.success(f"Conectado a {environment}" + (f" · cuenta {account.account_name} ({account.currency} {account.balance:,.2f})" if account else ""))
    except Exception as exc:
        st.session_state["capital_connected"] = False
        st.sidebar.error(f"Error al conectar: {exc}")

if not st.session_state["capital_connected"]:
    st.info("👈 Conecta tu cuenta de Capital.com desde la barra lateral para ver mercados, velas en vivo y operar.")
    st.stop()

client = get_client(environment, creds.api_key, creds.identifier, creds.password)
if not client.is_connected:
    st.session_state["capital_connected"] = False
    st.warning("La sesion se perdio (probablemente por inactividad). Vuelve a pulsar Conectar.")
    st.stop()

st.caption(
    "Nota: esta app es de un solo usuario local — si abres varias pestañas del navegador comparten la misma sesion de Capital.com."
)

_now_utc = datetime.now(timezone.utc)
render_data_status(to_new_york_time(_now_utc), current_session_label(_now_utc))

# -- Resumen de cuenta ---------------------------------------------------------------

st.markdown("### 💰 Resumen de cuenta")


@st.fragment(run_every=10)
def render_account_summary() -> None:
    try:
        client.keepalive_if_needed()
        account = client.get_account_summary()
        open_positions = client.get_open_positions()
    except Exception as exc:
        st.error(f"No se pudo obtener el resumen de cuenta: {exc}")
        return
    if account is None:
        st.warning("No se pudo determinar la cuenta activa.")
        return

    n_open = len(open_positions)
    pl_label = "P/L abierto" + (f" · {n_open} operacion{'es' if n_open != 1 else ''}" if n_open else "")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Cuenta", account.account_name, account.account_type)
    c2.metric("Saldo (Balance)", f"{account.balance:,.2f} {account.currency}")
    c3.metric("Disponible", f"{account.available:,.2f} {account.currency}")
    c4.metric(pl_label, f"{account.profit_loss:+,.2f} {account.currency}", delta=account.profit_loss)
    st.caption(
        f"ID de cuenta conectada: `{account.account_id}` — si tienes mas de una cuenta llamada "
        f"'{account.account_name}' en {environment}, compara este ID con el que ves en la app/web de Capital.com "
        "para confirmar que es la misma cuenta (el nombre por si solo no la distingue si esta duplicado)."
    )


render_account_summary()

# -- Seleccion de mercado ---------------------------------------------------------------

st.markdown("### 🔎 Seleccion de mercado")


def _set_search_term(term: str) -> None:
    st.session_state["capital_search_term"] = term


def _set_priority_asset(asset_class: str, search_term: str) -> None:
    st.session_state["capital_asset_class"] = asset_class
    st.session_state["capital_search_term"] = search_term


st.caption("⭐ Activos prioritarios de la estrategia (alta volatilidad/volumen):")
prio_cols = st.columns(len(config.CAPITAL_PRIORITY_ASSETS))
for prio_col, (prio_label, prio_spec) in zip(prio_cols, config.CAPITAL_PRIORITY_ASSETS.items()):
    prio_col.button(
        f"⭐ {prio_label}",
        key=f"priority_{prio_label}",
        on_click=_set_priority_asset,
        args=(prio_spec["asset_class"], prio_spec["search_term"]),
        width="stretch",
    )

class_col, search_col = st.columns([1, 2])
with class_col:
    asset_class = st.selectbox("Clase de activo", options=list(config.CAPITAL_ASSET_CLASSES.keys()), key="capital_asset_class")
with search_col:
    search_term = st.text_input("Filtrar por nombre o codigo (opcional, ej. ETH, EUR, GOLD...)", key="capital_search_term")

seeds = config.CAPITAL_PRESET_SEEDS.get(asset_class, [])
if seeds:
    st.caption("Atajos:")
    seed_cols = st.columns(len(seeds))
    for seed_col, seed in zip(seed_cols, seeds):
        seed_col.button(seed, key=f"seed_{asset_class}_{seed}", on_click=_set_search_term, args=(seed,), width="stretch")


@st.cache_data(ttl=60, show_spinner="Cargando instrumentos...")
def _browse_markets(_client, asset_class: str, search_term: str) -> tuple[list[dict], str | None]:
    try:
        return _client.browse_markets(asset_class, search_term=search_term, limit=config.CAPITAL_MARKET_BROWSE_LIMIT), None
    except Exception as exc:
        return [], str(exc)


markets, browse_error = _browse_markets(client, asset_class, search_term)

if browse_error:
    st.error(f"Error obteniendo instrumentos: {browse_error}")
elif not markets:
    st.caption("Sin resultados. Prueba con un atajo de arriba o escribe un termino de busqueda.")
else:
    st.markdown("##### ✅ ¿Qué activos son operables con el motor ahora mismo?")
    n_tradeable = sum(1 for m in markets if m.get("marketStatus") == "TRADEABLE")
    session_gate_on = st.session_state["capital_session_gate"]
    session_now = current_session_label(datetime.now(timezone.utc))
    engine_ready = (
        "🟢 armado" if st.session_state["capital_armed"] else "🔴 desarmado"
    )
    session_note = (
        (f"dentro de sesion ({session_now})" if session_now != "Fuera de sesion" else "fuera de Londres/Nueva York")
        if session_gate_on
        else "sin restriccion de sesion (filtro desactivado)"
    )
    st.caption(
        f"Un instrumento es operable por el motor si su mercado esta abierto (columna 'Operable' abajo, dato en "
        f"vivo de Capital.com) Y el motor esta armado Y — si el filtro de sesion esta activo — estas dentro de "
        f"Londres/Nueva York. Ahora mismo: motor {engine_ready}, {session_note}. "
        f"✅ {n_tradeable} de {len(markets)} instrumento(s) de {asset_class} con mercado abierto."
    )

    display_df = pd.DataFrame(
        [
            {
                "Epic": m.get("epic", ""),
                "Nombre": m.get("instrumentName", m.get("epic", "")),
                "Tipo": m.get("instrumentType", ""),
                "Operable": "{} {}".format(*_market_status_label(m.get("marketStatus", ""))),
                "Bid": m.get("bid"),
                "Offer": m.get("offer"),
            }
            for m in markets
        ]
    )
    st.dataframe(display_df, width="stretch", hide_index=True, height=250)

    options = {f"{m.get('instrumentName', m.get('epic'))} ({m.get('epic')})": m.get("epic") for m in markets}
    selected_label = st.selectbox("Elegir instrumento para operar", options=list(options.keys()), key="capital_market_pick")
    if st.button("Seleccionar instrumento"):
        st.session_state["capital_selected_epic"] = options[selected_label]
        st.session_state["capital_selected_name"] = selected_label

epic = st.session_state.get("capital_selected_epic")

# -- Reporte Ejecutivo ---------------------------------------------------------------

if epic:
    st.markdown("### 📋 Reporte Ejecutivo")

    @st.fragment(run_every=45)
    def render_executive_report() -> None:
        name = st.session_state.get("capital_selected_name", epic)
        now_utc = datetime.now(timezone.utc)

        try:
            client.keepalive_if_needed()
            mtf_prob = _mtf_probability_cached(client, environment, epic)
            institutional = _institutional_bias_cached(client, environment, epic)
            scalping = _scalping_snapshot_cached(client, environment, epic)
            market_status = _epic_market_status_cached(client, environment, epic)
            positions = client.get_open_positions()
        except Exception as exc:
            st.error(f"No se pudo generar el reporte ejecutivo: {exc}")
            return

        epic_positions = [p for p in positions if p.epic == epic]
        session_label = current_session_label(now_utc)

        env_badge_class = "eth-badge-live" if environment == "LIVE" else "eth-badge-demo"
        st.markdown(
            f'<div class="eth-card">'
            f'<div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:8px;">'
            f'<div><span style="font-size:1.3rem; font-weight:700;">{name}</span> '
            f'<span class="eth-badge {env_badge_class}" style="margin-left:8px;">{environment}</span></div>'
            f'<div style="color:{COLORS["text_muted"]}; font-size:0.82rem;">'
            f'Generado: {to_new_york_time(now_utc).strftime("%d/%m %H:%M")} (NY)</div>'
            f"</div></div>",
            unsafe_allow_html=True,
        )

        view = st.segmented_control(
            "Vista", ["Vista del CEO", "Vista del Analista"],
            default="Vista del CEO", key="exec_report_view", label_visibility="collapsed",
        )

        avg_txt = f"{mtf_prob['avg_probability']:.0f}%" if mtf_prob["avg_probability"] is not None else "sin datos"
        align_txt = "alineada" if mtf_prob["aligned"] else "sin alinear"
        session_txt = session_label.lower() if session_label != "Fuera de sesion" else "fuera de sesion"
        armed_txt = "armado" if st.session_state["capital_armed"] else "desarmado"
        bias_txt = institutional["macro_bias"]
        if epic_positions:
            total_pl = sum(p.profit_loss for p in epic_positions)
            currency = epic_positions[0].currency
            position_txt = f" {len(epic_positions)} posicion(es) abierta(s) en este activo con {total_pl:+,.2f} {currency}."
        else:
            position_txt = " Sin posiciones abiertas en este activo."
        summary = (
            f"{name}: confluencia {align_txt} con {avg_txt} de probabilidad promedio (5m/15m/1h), sesion "
            f"{session_txt}, motor {armed_txt}. Sesgo institucional {bias_txt}.{position_txt}"
        )
        st.markdown(
            f'<div class="eth-card" style="font-style:italic; color:{COLORS["text_secondary"]};">{summary}</div>',
            unsafe_allow_html=True,
        )

        if view == "Vista del Analista":
            _render_analyst_view(mtf_prob, institutional, scalping, name)
        else:
            _render_ceo_view(mtf_prob, institutional, market_status, epic_positions, session_label)

    render_executive_report()

# -- Monitor de velas en vivo ---------------------------------------------------------------

if epic:
    st.markdown(f"### 📉 Monitor en vivo — {st.session_state.get('capital_selected_name', epic)}")

    @st.fragment(run_every=10)
    def render_live_chart() -> None:
        try:
            client.keepalive_if_needed()
            candles = client.get_candles(epic, resolution=config.DEFAULT_CAPITAL_RESOLUTION, max_points=120)
        except Exception as exc:
            st.error(f"No se pudo obtener el precio: {exc}")
            return
        if candles.empty:
            st.warning("Sin datos de velas para este instrumento.")
            return
        fig = candlestick_chart(candles, title=f"{epic} — {config.DEFAULT_CAPITAL_RESOLUTION}")
        add_update_marker(fig, to_new_york_time(candles.index[-1]))
        st.plotly_chart(fig, width="stretch")

    render_live_chart()

    st.markdown("### 📊 Probabilidad de la zona activa")
    st.caption(
        "Confluencia 1h/15m/5m: probabilidad de continuacion de la zona mas reciente en cada "
        "temporalidad, comparada con analogos historicos y el desempeño de estructura reciente."
    )

    @st.fragment(run_every=60)
    def render_probability_panel() -> None:
        try:
            client.keepalive_if_needed()
            mtf_prob = _mtf_probability_cached(client, environment, epic)
        except Exception as exc:
            st.error(f"No se pudo calcular la probabilidad: {exc}")
            return
        pc1, pc2, pc3 = st.columns(3)
        for col, label in zip((pc1, pc2, pc3), ("1h", "15m", "5m")):
            entry = mtf_prob["per_timeframe"].get(label)
            if entry and entry["prob"]:
                fires = "🔥" * entry["prob"]["fires"] or "—"
                col.metric(f"{label} ({entry['kind']})", f"{entry['prob']['probability']:.0f}% {fires}", entry["prob"]["tier"])
            else:
                col.metric(label, "Sin datos")
        if mtf_prob["avg_probability"] is not None:
            align_msg = "✅ Alineadas" if mtf_prob["aligned"] else "⚠️ Sin alinear — evitar operar"
            st.markdown(f"**Probabilidad promedio: {mtf_prob['avg_probability']:.1f}%** · {align_msg}")

        _render_signal_detail(mtf_prob, st.session_state.get("capital_selected_name", epic))

    render_probability_panel()
else:
    st.info("Busca y selecciona un instrumento arriba para ver el monitor en vivo y poder operar.")

# -- Divergencia DXY (solo EUR/USD) ---------------------------------------------------------------

if epic and "EUR" in epic.upper() and "USD" in epic.upper():
    st.markdown("### 💵 Divergencia DXY (confirmacion institucional)")

    @st.fragment(run_every=30)
    def render_dxy_panel() -> None:
        try:
            client.keepalive_if_needed()
            pair_candles = client.get_candles(epic, resolution=config.DEFAULT_CAPITAL_RESOLUTION, max_points=120)
            dxy_candles = fetch_dxy(period="30d", interval=config.INTERVALS["15m"]["yfinance"])
        except Exception as exc:
            st.error(f"No se pudo obtener el DXY: {exc}")
            return
        if pair_candles.empty or dxy_candles.empty:
            st.caption("Sin datos suficientes para comparar con el DXY.")
            return

        divergence = detect_dxy_divergence(pair_candles, dxy_candles)
        if divergence is None:
            st.caption("Sin barridas de liquidez recientes en el DXY para comparar.")
        elif divergence["divergence"]:
            st.success(f"⚡ Divergencia DXY confirma sesgo {divergence['confirmed_bias']} para {epic}.")
        else:
            st.caption(f"Sin divergencia: {epic} se movio en linea con el DXY (correlacion inversa normal).")

    render_dxy_panel()

# -- Posiciones abiertas ---------------------------------------------------------------

st.markdown("### 📂 Posiciones abiertas")


@st.fragment(run_every=15)
def render_positions() -> None:
    try:
        client.keepalive_if_needed()
        positions = client.get_open_positions()
    except Exception as exc:
        st.error(f"No se pudieron obtener las posiciones: {exc}")
        return
    if not positions:
        st.caption("Sin posiciones abiertas.")
        return
    for pos in positions:
        cols = st.columns([2, 1, 1, 1, 1.4, 1])
        cols[0].write(f"**{pos.instrument_name}**  \n`{pos.epic}`")
        cols[1].markdown(
            f'<span class="eth-badge eth-badge-{"buy" if pos.direction == "BUY" else "sell"}">{pos.direction}</span>',
            unsafe_allow_html=True,
        )
        cols[2].write(f"{pos.size:g}")
        cols[3].write(f"{pos.open_level:,.2f}")
        pl_icon = "🟢" if pos.profit_loss >= 0 else "🔴"
        cols[4].write(f"{pl_icon} {pos.profit_loss:,.2f} {pos.currency}")
        if cols[5].button("Cerrar", key=f"close_{pos.deal_id}"):
            try:
                ref = client.close_position(pos.deal_id)
                client.confirm_deal(ref)
                st.success("Posicion cerrada.")
                st.rerun()
            except Exception as exc:
                st.error(f"No se pudo cerrar la posicion: {exc}")


render_positions()


@st.fragment(run_every=20)
def render_breakeven_monitor() -> None:
    """Gestiona automaticamente las posiciones abiertas por el motor automatico:

    - Si alcanzan un recorrido 1:1, O si a los `AUTO_TIME_LIMIT_MINUTES` ya avanzaron
      algo (aunque sea poco) a favor de su direccion, mueve el stop a break-even.
    - Regla de 45 minutos: si a los `AUTO_TIME_LIMIT_MINUTES` NO avanzaron nada a
      favor (siguen igual o peor que el precio de entrada), se CIERRAN por completo
      — la estructura no tiene suficiente fuerza o va en direccion contraria.

    Nunca toca posiciones manuales o preexistentes — solo las que estan en
    `capital_auto_opened_deals`."""
    tracked = st.session_state["capital_auto_opened_deals"]
    if not tracked:
        return
    try:
        client.keepalive_if_needed()
        positions = client.get_open_positions()
    except Exception as exc:
        st.error(f"Monitor de gestion automatica: error obteniendo posiciones: {exc}")
        return

    tracked.intersection_update({p.deal_id for p in positions})
    done = st.session_state["capital_breakeven_done"]

    for pos in positions:
        if pos.deal_id not in tracked or pos.deal_id in done or pos.stop_level is None:
            continue
        risk = abs(pos.open_level - pos.stop_level)
        if risk <= 0:
            continue
        target_1r = pos.open_level + risk if pos.direction == "BUY" else pos.open_level - risk
        reached_1r = (pos.direction == "BUY" and pos.current_level >= target_1r) or (
            pos.direction == "SELL" and pos.current_level <= target_1r
        )
        progressed = (pos.direction == "BUY" and pos.current_level > pos.open_level) or (
            pos.direction == "SELL" and pos.current_level < pos.open_level
        )
        elapsed_minutes = (
            (datetime.now(timezone.utc) - pos.created_at).total_seconds() / 60 if pos.created_at else None
        )
        time_rule = elapsed_minutes is not None and elapsed_minutes >= config.AUTO_TIME_LIMIT_MINUTES

        if time_rule and not reached_1r and not progressed:
            try:
                ref = client.close_position(pos.deal_id)
                client.confirm_deal(ref)
                tracked.discard(pos.deal_id)
                st.session_state["capital_automation_log"].insert(
                    0,
                    {
                        "Hora": datetime.now().strftime("%H:%M:%S"),
                        "Señal": f"Cierre automatico ({config.AUTO_TIME_LIMIT_MINUTES} min sin avance a favor)",
                        "Direccion": pos.direction,
                        "Resultado": f"Posicion cerrada en {pos.current_level:,.2f}",
                    },
                )
                st.warning(
                    f"⏱️ {pos.instrument_name} cerrada por regla de {config.AUTO_TIME_LIMIT_MINUTES} min "
                    f"(sin avance a favor desde {pos.open_level:,.2f})."
                )
            except Exception as exc:
                st.error(f"No se pudo cerrar {pos.instrument_name} por regla de tiempo: {exc}")
            continue

        if not (reached_1r or time_rule):
            continue
        motivo = (
            "1:1 alcanzado"
            if reached_1r
            else f"{config.AUTO_TIME_LIMIT_MINUTES} min con avance parcial (regla de tiempo)"
        )
        try:
            ref = client.update_position(pos.deal_id, stop_level=pos.open_level)
            client.confirm_deal(ref)
            done.add(pos.deal_id)
            st.session_state["capital_automation_log"].insert(
                0,
                {
                    "Hora": datetime.now().strftime("%H:%M:%S"),
                    "Señal": f"Break-even automatico ({motivo})",
                    "Direccion": pos.direction,
                    "Resultado": f"SL movido a {pos.open_level:,.2f}",
                },
            )
            st.success(f"🔒 Break-even aplicado en {pos.instrument_name} ({motivo}): SL movido a {pos.open_level:,.2f}")
        except Exception as exc:
            st.error(f"No se pudo mover a break-even {pos.instrument_name}: {exc}")


render_breakeven_monitor()

# -- Ticket de orden manual ---------------------------------------------------------------

st.markdown("### 🎫 Ticket de orden manual")

if not epic:
    st.caption("Selecciona un instrumento para poder operar.")
else:
    _price_ref = None
    try:
        _account_ref = client.get_account_summary()
        _price_ref_df = client.get_candles(epic, resolution=config.DEFAULT_CAPITAL_RESOLUTION, max_points=1)
        if _account_ref and not _price_ref_df.empty:
            _price_ref = float(_price_ref_df["close"].iloc[-1])
            _size_hint = suggested_size(_account_ref.balance, config.ICT_RISK_PCT_DEFAULT, _price_ref, _price_ref * 0.985)
            if _size_hint:
                st.caption(
                    f"💡 Tamaño de referencia para arriesgar {config.ICT_RISK_PCT_DEFAULT:.0f}% del saldo "
                    f"({_account_ref.balance:,.2f} {_account_ref.currency}) con SL del 1.5%: ~{_size_hint:,.4g} "
                    "(aproximado — confirma el riesgo real en Capital.com antes de enviar)."
                )
    except Exception:
        pass  # la sugerencia es informativa; nunca debe bloquear el ticket

    # El modo (unidades vs % balance, porcentaje vs precio absoluto) vive FUERA del
    # form: un st.form no rehace el script hasta enviarse, asi que el selector de
    # modo necesita su propio rerun inmediato para intercambiar los campos que se
    # muestran dentro del form.
    mc1, mc2 = st.columns(2)
    size_mode = mc1.radio("Tamaño por:", ["Unidades", "% del balance disponible"], horizontal=True, key="manual_size_mode")
    sltp_mode = mc2.radio("Stoploss/Take Profit por:", ["Porcentaje (%)", "Precio absoluto"], horizontal=True, key="manual_sltp_mode")

    # Paso/formato de precio escalados al precio real del instrumento -- un EUR/USD
    # (~1.08) necesita 5 decimales, un BTC/USD (~65000) solo 2.
    if _price_ref and _price_ref >= 1000:
        _price_decimals = 2
    elif _price_ref and _price_ref >= 10:
        _price_decimals = 3
    elif _price_ref and _price_ref >= 1:
        _price_decimals = 5
    else:
        _price_decimals = 6
    _price_step = round(10**-_price_decimals, _price_decimals)
    _price_format = f"%.{_price_decimals}f"

    with st.form("manual_order_form"):
        oc1, oc2, oc3 = st.columns(3)
        direction = oc1.radio("Direccion", ["BUY", "SELL"], horizontal=True, key="manual_direction")
        if size_mode == "Unidades":
            size_input = oc2.number_input("Tamaño (unidades)", min_value=0.01, value=1.0, step=0.01, key="manual_size_units")
        else:
            size_input = oc2.number_input(
                "Tamaño (% del balance disponible)", min_value=0.1, value=5.0, step=0.5, key="manual_size_pct"
            )
        guaranteed = oc3.checkbox("Stop garantizado", value=False, key="manual_guaranteed")

        lc1, lc2 = st.columns(2)
        if sltp_mode == "Porcentaje (%)":
            sl_input = lc1.number_input("Stoploss (%, 0 = sin SL)", min_value=0.0, value=1.5, step=0.1, key="manual_sl_pct")
            tp_input = lc2.number_input("Take Profit (%, 0 = sin TP)", min_value=0.0, value=3.0, step=0.1, key="manual_tp_pct")
            st.caption("El % se aplica sobre el precio actual del instrumento para calcular la distancia que exige Capital.com.")
        else:
            sl_input = lc1.number_input(
                "Stoploss (precio, 0 = sin SL)", min_value=0.0, value=0.0, step=_price_step, format=_price_format, key="manual_sl_price"
            )
            tp_input = lc2.number_input(
                "Take Profit (precio, 0 = sin TP)", min_value=0.0, value=0.0, step=_price_step, format=_price_format, key="manual_tp_price"
            )
            st.caption("Precio absoluto del nivel (no distancia): debe quedar del lado correcto segun la direccion — Capital.com rechaza la orden si no.")

        if size_mode == "% del balance disponible":
            st.caption(
                "El tamaño en unidades se calcula al enviar la orden como (balance disponible × %) / precio actual "
                "— aproximado, sin considerar apalancamiento; confirma la exposicion real en Capital.com."
            )

        confirm_live = True
        if environment == "LIVE":
            st.markdown(
                '<span class="eth-badge eth-badge-live">⚠️ Esta orden se ejecutara con DINERO REAL</span>',
                unsafe_allow_html=True,
            )
            confirm_live = st.checkbox("Confirmo que esta es una cuenta REAL y quiero enviar esta orden")

        submitted = st.form_submit_button("Enviar orden", width="stretch")

    if submitted:
        if environment == "LIVE" and not confirm_live:
            st.error("Debes marcar la confirmacion para operar en cuenta REAL.")
        else:
            try:
                ref_candles = client.get_candles(epic, resolution=config.DEFAULT_CAPITAL_RESOLUTION, max_points=1)
                if ref_candles.empty:
                    raise CapitalError("No se pudo obtener el precio actual del instrumento para calcular SL/TP/tamaño.")
                ref_price = float(ref_candles["close"].iloc[-1])

                if size_mode == "Unidades":
                    size = size_input
                else:
                    account_now = client.get_account_summary()
                    if not account_now or account_now.available <= 0:
                        raise CapitalError("No se pudo obtener el balance disponible para calcular el tamaño.")
                    size = (account_now.available * size_input / 100) / ref_price

                if sltp_mode == "Porcentaje (%)":
                    stop_kwargs = {"stop_distance": (ref_price * sl_input / 100) or None}
                    profit_kwargs = {"profit_distance": (ref_price * tp_input / 100) or None}
                else:
                    stop_kwargs = {"stop_level": sl_input or None}
                    profit_kwargs = {"profit_level": tp_input or None}

                ref = client.place_order(
                    epic=epic,
                    direction=direction,
                    size=size,
                    guaranteed_stop=guaranteed,
                    **stop_kwargs,
                    **profit_kwargs,
                )
                result = client.confirm_deal(ref)
                st.success(f"Orden enviada y confirmada: {result.get('dealStatus', 'OK')} (tamaño: {size:,.4g})")
                # "Posiciones abiertas" ya se renderizo mas arriba en este mismo
                # script run (antes de que esta orden existiera) -- sin este rerun,
                # la posicion recien abierta no aparece ahi hasta el siguiente
                # refresco automatico (hasta 15s despues). Mismo patron que ya usa
                # el boton "Cerrar" en render_positions().
                st.rerun()
            except Exception as exc:
                st.error(_order_error_message(exc))

# -- Motor semi-automatico ---------------------------------------------------------------

st.markdown("### 🤖 Motor semi-automatico")
st.caption("Apagado por defecto. Nunca se mantiene armado entre reinicios de la app: vive solo en esta sesion del navegador.")

with st.expander("Configurar y armar motor automatico", expanded=False):
    rule = st.selectbox("Señal que dispara la orden", RULES, key="capital_rule")
    threshold = st.slider("Umbral de score (solo regla Scalping)", 0.1, 1.0, 0.5, 0.05, key="capital_threshold")
    auto_size = st.number_input("Tamaño por operacion automatica", min_value=0.01, value=1.0, step=0.01, key="capital_auto_size")
    auto_sl = st.number_input("Stoploss (%)", min_value=0.1, value=1.5, step=0.1, key="capital_auto_sl")
    auto_tp = st.number_input("Take Profit (%)", min_value=0.1, value=3.0, step=0.1, key="capital_auto_tp")
    st.caption("El % se aplica sobre el precio de cierre de la ultima vela evaluada.")
    max_trades = st.number_input(
        "Maximo de operaciones automaticas por sesion",
        min_value=1, max_value=20, value=config.DEFAULT_MAX_AUTO_TRADES_PER_SESSION, key="capital_max_trades",
    )
    st.caption(
        f"Regla 1111: ademas de este tope, el motor nunca abre mas de "
        f"{config.DEFAULT_MAX_AUTO_TRADES_PER_DAY} operacion(es) automatica(s) por dia calendario."
    )
    st.checkbox(
        "🕒 Restringir solo a sesiones operativas (Londres 6-9 UTC / Nueva York 11-16 UTC)",
        value=True,
        key="capital_session_gate",
        help="Desactivalo si quieres que el motor evalue senales fuera de Londres/Nueva York. Recomendado "
        "dejarlo activo: fuera de estas ventanas la liquidez suele ser mas baja.",
    )
    st.checkbox(
        "⚠️ Pausar por noticias de alto impacto",
        value=False,
        key="capital_news_pause",
        help="Activalo manualmente antes de una noticia de alto impacto — no hay deteccion automatica de calendario economico.",
    )

    if epic:
        try:
            _account_auto = client.get_account_summary()
            _ref_auto_df = client.get_candles(epic, resolution=config.DEFAULT_CAPITAL_RESOLUTION, max_points=1)
            if _account_auto and not _ref_auto_df.empty:
                _price_auto = float(_ref_auto_df["close"].iloc[-1])
                _size_hint_auto = suggested_size(_account_auto.balance, config.ICT_RISK_PCT_DEFAULT, _price_auto, _price_auto * (1 - auto_sl / 100))
                if _size_hint_auto:
                    st.caption(f"💡 Tamaño de referencia (1% de riesgo, SL {auto_sl:.1f}%): ~{_size_hint_auto:,.4g}")
        except Exception:
            pass

    live_confirm_text = ""
    can_arm = True
    if environment == "LIVE":
        st.warning("Vas a armar automatizacion sobre una CUENTA REAL. Escribe ARMAR para poder activarla.")
        live_confirm_text = st.text_input("Escribe ARMAR para confirmar", key="capital_arm_confirm_text")
        can_arm = live_confirm_text.strip().upper() == "ARMAR"

    armed_toggle = st.toggle(
        "Motor automatico ARMADO",
        value=st.session_state["capital_armed"] and can_arm,
        disabled=not can_arm,
    )
    st.session_state["capital_armed"] = bool(armed_toggle and can_arm)

if st.session_state["capital_armed"]:
    st.markdown('<span class="eth-badge eth-badge-live">🤖 ARMADO</span>', unsafe_allow_html=True)
else:
    st.markdown('<span class="eth-badge eth-badge-demo">⏸️ DESARMADO</span>', unsafe_allow_html=True)


@st.cache_data(ttl=60, show_spinner=False)
def _preview_candles(_client, environment: str, epic: str, resolution: str, max_points: int) -> pd.DataFrame:
    return _client.get_candles(epic, resolution=resolution, max_points=max_points)


@st.fragment
def render_auto_engine_preview() -> None:
    """Vista previa opcional (no corre sola: solo se calcula mientras el toggle esta
    activo, y vive en su propio fragment para no recalcularse cuando otros
    fragments de la pagina — posiciones, break-even, motor — hacen su propio
    refresco periodico). Muestra un candlestick real con los SL/TP configurados y,
    segun la regla activa, donde se habria disparado historicamente con el
    umbral/RR actual."""
    st.toggle(
        "🔍 Vista previa de la configuracion (grafico de referencia)",
        key="capital_preview_open",
        help="Candlestick real con los SL/TP configurados y donde se habria disparado historicamente la "
        "regla elegida con el umbral/RR actual.",
    )
    if not st.session_state["capital_preview_open"]:
        return
    if not epic:
        st.caption("Selecciona un instrumento para ver la vista previa.")
        return

    rule = st.session_state.get("capital_rule", RULES[0])
    threshold = st.session_state.get("capital_threshold", 0.5)
    sl_pct = st.session_state.get("capital_auto_sl", 1.5)
    tp_pct = st.session_state.get("capital_auto_tp", 3.0)
    # Misma resolucion que usa el motor en vivo para esta regla: M15 para Scalping
    # (config.DEFAULT_CAPITAL_RESOLUTION), HOUR para SMC Institucional (la
    # temporalidad de estructura en `run_auto_engine`).
    resolution = config.DEFAULT_CAPITAL_RESOLUTION if rule == RULES[0] else "HOUR"

    try:
        candles = _preview_candles(client, environment, epic, resolution, 200)
    except Exception as exc:
        st.error(f"Vista previa: error obteniendo velas: {exc}")
        return
    if candles.empty or len(candles) < 60:
        st.caption("No hay suficientes velas para la vista previa en esta resolucion.")
        return

    last_close = float(candles["close"].iloc[-1])
    fig = candlestick_chart(
        candles, title=f"Vista previa — {st.session_state.get('capital_selected_name', epic)} ({resolution})"
    )
    add_auto_engine_reference_levels(fig, last_close, sl_pct, tp_pct)

    if rule == RULES[0]:
        scores = vectorized_scalping_score(compute_indicators(candles))
        add_scalping_signal_markers(fig, candles, scores, threshold)
        st.caption(
            f"Triangulos: velas donde el score historico habria cruzado el umbral actual ({threshold:+.2f}) "
            f"sobre velas {resolution} (la misma resolucion que evalua el motor en vivo para esta regla). "
            "Lineas: SL/TP hipoteticos con los % configurados aplicados sobre el ultimo cierre."
        )
    else:
        setups = historical_qualified_setups(candles, min_rr=config.ICT_MIN_RR)
        add_historical_setup_markers(fig, candles, setups)
        st.caption(
            f"Triangulos: entradas historicas que habria disparado la regla SMC Institucional (retest de zona "
            f"con RR >= {config.ICT_MIN_RR:g}) sobre velas {resolution} — la misma temporalidad de estructura "
            "que usa el motor en vivo. Lineas: SL/TP hipoteticos con los % configurados."
        )

    st.plotly_chart(fig, width="stretch", key="capital_preview_chart")


render_auto_engine_preview()

if epic and st.session_state["capital_armed"]:

    @st.fragment(run_every=15)
    def run_auto_engine() -> None:
        if not st.session_state["capital_armed"]:
            return
        if st.session_state["capital_trades_this_session"] >= st.session_state["capital_max_trades"]:
            st.warning("Se alcanzo el maximo de operaciones automaticas de la sesion. Motor en pausa.")
            return

        if st.session_state["capital_news_pause"]:
            st.caption("⚠️ Pausado manualmente por noticias de alto impacto.")
            return

        now_utc = datetime.now(timezone.utc)
        if st.session_state["capital_session_gate"] and not in_high_liquidity_session(now_utc):
            st.caption("Fuera de sesion operativa (Londres 6-9 UTC / Nueva York 11-16 UTC). Motor en espera.")
            return
        if st.session_state["capital_last_auto_trade_date"] == now_utc.date():
            st.caption("Ya se realizo la operacion automatica permitida hoy (regla 1111: 1 operacion por dia). Motor en espera.")
            return

        try:
            client.keepalive_if_needed()
            candles = client.get_candles(epic, resolution=config.DEFAULT_CAPITAL_RESOLUTION, max_points=120)
        except Exception as exc:
            st.error(f"Motor automatico: error obteniendo velas: {exc}")
            return
        if candles.empty or len(candles) < 60:
            return

        last_bar = candles.index[-1]
        if st.session_state["capital_last_evaluated_bar"] == last_bar:
            st.caption(f"Motor activo. Esperando la proxima vela ({last_bar}).")
            return
        st.session_state["capital_last_evaluated_bar"] = last_bar

        extra_candles = None
        if st.session_state["capital_rule"] == RULES[1]:
            try:
                extra_candles = {
                    "bias": client.get_candles(epic, resolution="DAY", max_points=120),
                    "structure": client.get_candles(epic, resolution="HOUR", max_points=120),
                }
            except Exception as exc:
                st.error(f"Motor automatico: error obteniendo velas de sesgo/estructura: {exc}")
                return

        triggered, direction, reason = evaluate_rule(
            st.session_state["capital_rule"], candles, st.session_state["capital_threshold"], extra_candles=extra_candles
        )
        if not triggered:
            st.caption(f"Motor activo. Sin señal en la vela {last_bar}.")
            return

        ref_price = float(candles["close"].iloc[-1])
        try:
            ref = client.place_order(
                epic=epic,
                direction=direction,
                size=st.session_state["capital_auto_size"],
                stop_distance=ref_price * st.session_state["capital_auto_sl"] / 100,
                profit_distance=ref_price * st.session_state["capital_auto_tp"] / 100,
            )
            result = client.confirm_deal(ref)
            st.session_state["capital_trades_this_session"] += 1
            st.session_state["capital_last_auto_trade_date"] = now_utc.date()
            affected = result.get("affectedDeals") or []
            if affected and affected[0].get("dealId"):
                st.session_state["capital_auto_opened_deals"].add(affected[0]["dealId"])
            st.session_state["capital_automation_log"].insert(
                0, {"Hora": datetime.now().strftime("%H:%M:%S"), "Señal": reason, "Direccion": direction, "Resultado": result.get("dealStatus", "OK")}
            )
            st.success(f"Orden automatica enviada: {direction} {epic} — {reason}")
            # Mismo motivo que en el ticket manual: "Posiciones abiertas" se
            # renderiza mas arriba en el script y no veria esta posicion nueva
            # hasta su propio refresco de hasta 15s sin este rerun explicito.
            st.rerun()
        except Exception as exc:
            st.session_state["capital_automation_log"].insert(
                0, {"Hora": datetime.now().strftime("%H:%M:%S"), "Señal": reason, "Direccion": direction, "Resultado": f"ERROR: {exc}"}
            )
            st.error(f"Motor automatico: {_order_error_message(exc)}")

    run_auto_engine()

if st.session_state["capital_automation_log"]:
    st.markdown("##### 📜 Log de automatizacion")
    st.dataframe(pd.DataFrame(st.session_state["capital_automation_log"]), width="stretch", hide_index=True)
