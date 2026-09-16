import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import streamlit as st

from core import config
from core.capital_client import CapitalError, get_client
from core.strategy import current_state, generate_signals
from ui.charts import add_update_marker, strategy_chart
from ui.theme import COLORS, inject_css

inject_css()


def _market_status_label(status: str) -> tuple[str, str]:
    return config.CAPITAL_MARKET_STATUS_LABELS.get(status, ("❓", status or "Desconocido"))


def _order_error_message(exc: Exception) -> str:
    text = str(exc)
    if any(term in text.lower() for term in ("stoploss", "minvalue", "profit")):
        return (
            f"{text}\n\n💡 Capital.com exige una distancia minima de SL para este instrumento. "
            "Prueba un instrumento/temporalidad con mayor volatilidad o revisa el pivote de SL calculado."
        )
    return f"No se pudo enviar la orden: {text}"


st.title("💹 Terminal — WMA(14) + Filtro RSI(14)")
st.caption(
    "Conecta tu cuenta de Capital.com, elige entorno y cuenta, busca un instrumento y observa/opera la "
    "estrategia. El login nunca ocurre solo: siempre lo dispara el boton Conectar."
)

creds = config.get_capital_credentials()

st.session_state.setdefault("capital_environment", creds.default_environment if creds.default_environment in ("DEMO", "LIVE") else "DEMO")
st.session_state.setdefault("capital_connected", False)
st.session_state.setdefault("capital_active_account_id", None)
st.session_state.setdefault("capital_armed", False)
st.session_state.setdefault("capital_trades_this_session", 0)
st.session_state.setdefault("capital_automation_log", [])
st.session_state.setdefault("capital_last_evaluated_bar", None)
st.session_state.setdefault("capital_auto_opened_deals", set())

# -- Sidebar: conexion ---------------------------------------------------------------

st.sidebar.markdown("### 🔐 Conexion Capital.com")

if not config.capital_credentials_present():
    st.sidebar.error("Faltan credenciales en capital_wma_rsi_trader/.env (CAPITAL_API_KEY / CAPITAL_API_USER / CAPITAL_API_PASSWORD).")

environment = st.sidebar.selectbox("Entorno", options=["DEMO", "LIVE"], key="capital_environment")

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
        st.session_state["capital_connected"] = True
        st.session_state["capital_active_account_id"] = client.account_id
        st.sidebar.success(f"Conectado a {environment}.")
    except Exception as exc:
        st.session_state["capital_connected"] = False
        st.sidebar.error(f"Error al conectar: {exc}")

if not st.session_state["capital_connected"]:
    st.info("👈 Conecta tu cuenta de Capital.com desde la barra lateral para ver mercados, velas en vivo y operar.")
    st.stop()

client = get_client(environment, creds.api_key, creds.identifier, creds.password)
if not client.is_connected:
    st.session_state["capital_connected"] = False
    st.warning("La sesion se perdio (reinicio de la app). Vuelve a pulsar Conectar.")
    st.stop()

# -- Seleccion de cuenta ---------------------------------------------------------------
# Desplegable (no texto libre) para no depender de escribir el nombre exacto -- si hay
# varias cuentas con el mismo nombre en Capital.com (pasa con cuentas demo duplicadas),
# el ID de cuenta que se muestra en cada opcion es lo unico que las distingue de forma
# inequivoca.


@st.cache_data(ttl=30, show_spinner=False)
def _list_accounts_cached(_client, environment: str) -> list:
    return _client.list_accounts()


def _account_label(acc) -> str:
    return f"{acc.account_name} ({acc.account_type}) · {acc.currency} {acc.balance:,.2f} · ID {acc.account_id}"


try:
    accounts = _list_accounts_cached(client, environment)
except Exception as exc:
    accounts = []
    st.sidebar.error(f"No se pudieron listar las cuentas: {exc}")

if accounts:
    labels = [_account_label(a) for a in accounts]
    id_by_label = {lbl: a.account_id for lbl, a in zip(labels, accounts)}

    # Clave con el entorno adentro: al cambiar DEMO<->LIVE las cuentas (y sus balances)
    # son otras, asi el widget arranca en limpio en vez de arrastrar una seleccion que
    # ya no existe en el entorno nuevo.
    account_key = f"capital_account_select_{environment}"
    if account_key not in st.session_state:
        preferred = next((a for a in accounts if a.account_name.strip().lower() == creds.default_account_name.strip().lower()), None)
        current = next((a for a in accounts if a.account_id == st.session_state["capital_active_account_id"]), None)
        st.session_state[account_key] = _account_label(current or preferred or accounts[0])

    selected_label = st.sidebar.selectbox("Cuenta", options=labels, key=account_key)
    selected_id = id_by_label[selected_label]

    if selected_id != st.session_state["capital_active_account_id"]:
        try:
            client.switch_account(selected_id)
            st.session_state["capital_active_account_id"] = selected_id
            st.rerun()
        except Exception as exc:
            st.sidebar.error(f"No se pudo cambiar de cuenta: {exc}")
else:
    st.sidebar.caption("Sin cuentas disponibles en este entorno.")

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
    st.caption(f"ID de cuenta conectada: `{account.account_id}`")


render_account_summary()

# -- Seleccion de mercado ---------------------------------------------------------------

st.markdown("### 🔎 Seleccion de mercado")


def _set_search_term(term: str) -> None:
    st.session_state["capital_search_term"] = term


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
        # on_click (no un "if button:" con asignacion directa a session_state despues):
        # el text_input de arriba ya se instancio con key="capital_search_term" en este
        # mismo script run, y Streamlit prohibe reescribir el session_state de un widget
        # ya instanciado -- el callback SI corre antes de que los widgets se vuelvan a
        # crear en el proximo rerun, asi que ahi si es seguro.
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
    n_tradeable = sum(1 for m in markets if m.get("marketStatus") == "TRADEABLE")
    st.caption(f"{len(markets)} instrumento(s) en {asset_class} · ✅ {n_tradeable} operable(s) ahora mismo.")
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
    selected_label = st.selectbox("Elegir instrumento", options=list(options.keys()), key="capital_market_pick")
    if st.button("Seleccionar instrumento"):
        st.session_state["capital_selected_epic"] = options[selected_label]
        st.session_state["capital_selected_name"] = selected_label

epic = st.session_state.get("capital_selected_epic")

if not epic:
    st.info("Busca y selecciona un instrumento arriba para ver el grafico y poder operar.")
    st.stop()

# -- Temporalidad ---------------------------------------------------------------

suggested = config.SUGGESTED_RESOLUTION_BY_CLASS.get(asset_class, config.DEFAULT_CAPITAL_RESOLUTION)
st.session_state.setdefault("capital_resolution", suggested)
resolution = st.selectbox(
    "Temporalidad (sugerida segun la clase de activo, editable)",
    options=config.CAPITAL_RESOLUTIONS, key="capital_resolution",
    help=f"Sugerida para {asset_class}: {suggested}",
)

# -- Grafico + estado de la maquina ---------------------------------------------------------------

st.markdown(f"### 📊 {st.session_state.get('capital_selected_name', epic)} — {resolution}")


@st.cache_data(ttl=20, show_spinner=False)
def _candles_cached(_client, environment: str, epic: str, resolution: str) -> pd.DataFrame:
    return _client.get_candles(epic, resolution=resolution, max_points=300)


@st.fragment(run_every=15)
def render_chart_and_state() -> None:
    try:
        client.keepalive_if_needed()
        df = _candles_cached(client, environment, epic, resolution)
    except Exception as exc:
        st.error(f"No se pudo obtener el precio: {exc}")
        return
    if df.empty or len(df) < config.WMA_PERIOD + 5:
        st.warning("Sin velas suficientes para este instrumento/temporalidad.")
        return

    signals = generate_signals(df)
    state = current_state(signals)

    sc1, sc2, sc3, sc4 = st.columns(4)
    pos_label = {"flat": "Sin posicion", "long": "LONG", "short": "SHORT"}[state["position"]]
    pos_badge = {"flat": "eth-badge-neutral", "long": "eth-badge-buy", "short": "eth-badge-sell"}[state["position"]]
    sc1.markdown(f"**Posicion**<br><span class='eth-badge {pos_badge}'>{pos_label}</span>", unsafe_allow_html=True)

    bias_label = {"buy": "Zona de compra (RSI < 40)", "sell": "Zona de venta (RSI > 60)", "none": "Zona neutra (40-60)"}[state["rsi_bias"]]
    bias_badge = {"buy": "eth-badge-buy", "sell": "eth-badge-sell", "none": "eth-badge-neutral"}[state["rsi_bias"]]
    sc2.markdown(f"**Filtro RSI**<br><span class='eth-badge {bias_badge}'>{bias_label}</span>", unsafe_allow_html=True)

    wma_label = {1: "Ascendente ↑", -1: "Descendente ↓", 0: "Plana"}[state["wma_dir"]]
    sc3.markdown(f"**Direccion WMA**<br>{wma_label}", unsafe_allow_html=True)

    sl_txt = f"{state['stop_loss']:,.5g}" if state["stop_loss"] is not None and pd.notna(state["stop_loss"]) else "—"
    sc4.markdown(f"**Stop Loss vigente**<br>{sl_txt}", unsafe_allow_html=True)

    fig = strategy_chart(signals.tail(200), title=f"{epic} ({resolution})", buy_level=config.RSI_BUY_LEVEL, sell_level=config.RSI_SELL_LEVEL)
    add_update_marker(fig, signals.index[-1].to_pydatetime())
    st.plotly_chart(fig, width="stretch")


render_chart_and_state()

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
        cols[3].write(f"{pos.open_level:,.5g}")
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

# -- Ticket de orden manual ---------------------------------------------------------------

st.markdown("### 🎫 Ticket de orden manual")

with st.form("manual_order_form"):
    oc1, oc2, oc3 = st.columns(3)
    direction = oc1.radio("Direccion", ["BUY", "SELL"], horizontal=True)
    size = oc2.number_input("Tamaño (unidades)", min_value=0.0001, value=0.01, step=0.0001, format="%.4f")
    guaranteed = oc3.checkbox("Stop garantizado", value=False)

    lc1, lc2 = st.columns(2)
    sl_price = lc1.number_input("Stoploss (precio absoluto, 0 = sin SL)", min_value=0.0, value=0.0, step=0.00001, format="%.5f")
    st.caption("Sin Take Profit: la estrategia cierra por SL o por señal contraria, no por objetivo fijo.")

    confirm_live = True
    if environment == "LIVE":
        st.markdown('<span class="eth-badge eth-badge-live">⚠️ Esta orden se ejecutara con DINERO REAL</span>', unsafe_allow_html=True)
        confirm_live = st.checkbox("Confirmo que esta es una cuenta REAL y quiero enviar esta orden")

    submitted = st.form_submit_button("Enviar orden", width="stretch")

if submitted:
    if environment == "LIVE" and not confirm_live:
        st.error("Debes marcar la confirmacion para operar en cuenta REAL.")
    else:
        try:
            ref = client.place_order(
                epic=epic, direction=direction, size=size,
                stop_level=sl_price or None, guaranteed_stop=guaranteed,
            )
            result = client.confirm_deal(ref)
            st.success(f"Orden enviada y confirmada: {result.get('dealStatus', 'OK')}")
            st.rerun()
        except Exception as exc:
            st.error(_order_error_message(exc))

# -- Motor semi-automatico ---------------------------------------------------------------

st.markdown("### 🤖 Motor semi-automatico")
st.caption(
    "Apagado por defecto. Evalua la ULTIMA vela cerrada con la misma maquina de estados del grafico "
    "(WMA(14) + filtro RSI(14)) y opera con tamaño fijo y el SL del pivote calculado. Nunca se mantiene "
    "armado entre reinicios de la app: vive solo en esta sesion del navegador."
)

with st.expander("Configurar y armar motor automatico", expanded=False):
    auto_size = st.number_input("Tamaño por operacion automatica", min_value=0.0001, value=0.01, step=0.0001, format="%.4f", key="capital_auto_size")
    max_trades = st.number_input(
        "Maximo de operaciones automaticas por sesion", min_value=1, max_value=50,
        value=config.DEFAULT_MAX_AUTO_TRADES_PER_SESSION, key="capital_max_trades",
    )

    live_confirm_text = ""
    can_arm = True
    if environment == "LIVE":
        st.warning("Vas a armar automatizacion sobre una CUENTA REAL. Escribe ARMAR para poder activarla.")
        live_confirm_text = st.text_input("Escribe ARMAR para confirmar", key="capital_arm_confirm_text")
        can_arm = live_confirm_text.strip().upper() == "ARMAR"

    armed_toggle = st.toggle("Motor automatico ARMADO", value=st.session_state["capital_armed"] and can_arm, disabled=not can_arm)
    st.session_state["capital_armed"] = bool(armed_toggle and can_arm)

if st.session_state["capital_armed"]:
    st.markdown('<span class="eth-badge eth-badge-live">🤖 ARMADO</span>', unsafe_allow_html=True)
else:
    st.markdown('<span class="eth-badge eth-badge-demo">⏸️ DESARMADO</span>', unsafe_allow_html=True)

if st.session_state["capital_armed"]:

    @st.fragment(run_every=15)
    def run_auto_engine() -> None:
        if not st.session_state["capital_armed"]:
            return
        if st.session_state["capital_trades_this_session"] >= st.session_state["capital_max_trades"]:
            st.warning("Se alcanzo el maximo de operaciones automaticas de la sesion. Motor en pausa.")
            return

        try:
            client.keepalive_if_needed()
            candles = client.get_candles(epic, resolution=resolution, max_points=300)
        except Exception as exc:
            st.error(f"Motor automatico: error obteniendo velas: {exc}")
            return
        if candles.empty or len(candles) < config.WMA_PERIOD + 5:
            return

        signals = generate_signals(candles)
        last_bar = signals.index[-1]
        if st.session_state["capital_last_evaluated_bar"] == last_bar:
            st.caption(f"Motor activo. Esperando la proxima vela ({last_bar}).")
            return
        st.session_state["capital_last_evaluated_bar"] = last_bar

        last = signals.iloc[-1]
        sig = last["signal"]
        if pd.isna(sig):
            st.caption(f"Motor activo. Sin señal en la vela {last_bar}.")
            return

        tracked = st.session_state["capital_auto_opened_deals"]

        if sig == "SL_CLOSE":
            try:
                positions = client.get_open_positions()
            except Exception as exc:
                st.error(f"Motor automatico: error obteniendo posiciones para cerrar por SL: {exc}")
                return
            for pos in positions:
                if pos.epic == epic and pos.deal_id in tracked:
                    try:
                        ref = client.close_position(pos.deal_id)
                        client.confirm_deal(ref)
                        tracked.discard(pos.deal_id)
                        st.session_state["capital_automation_log"].insert(
                            0, {"Hora": datetime.now().strftime("%H:%M:%S"), "Señal": "SL_CLOSE", "Resultado": "Posicion cerrada por SL"}
                        )
                        st.rerun()
                    except Exception as exc:
                        st.error(f"Motor automatico: no se pudo cerrar por SL: {exc}")
            return

        if sig not in ("BUY_OPEN", "SELL_OPEN", "REVERSE_TO_LONG", "REVERSE_TO_SHORT"):
            return

        direction = "BUY" if sig in ("BUY_OPEN", "REVERSE_TO_LONG") else "SELL"
        sl = last["stop_loss"]
        if pd.isna(sl):
            return

        # Reversa: si hay una posicion contraria abierta por el motor, cerrarla primero.
        if sig in ("REVERSE_TO_LONG", "REVERSE_TO_SHORT"):
            try:
                positions = client.get_open_positions()
                for pos in positions:
                    if pos.epic == epic and pos.deal_id in tracked and pos.direction != direction:
                        ref = client.close_position(pos.deal_id)
                        client.confirm_deal(ref)
                        tracked.discard(pos.deal_id)
            except Exception as exc:
                st.error(f"Motor automatico: error cerrando la posicion contraria antes de revertir: {exc}")
                return

        try:
            ref = client.place_order(epic=epic, direction=direction, size=st.session_state["capital_auto_size"], stop_level=float(sl))
            result = client.confirm_deal(ref)
            st.session_state["capital_trades_this_session"] += 1
            affected = result.get("affectedDeals") or []
            if affected and affected[0].get("dealId"):
                tracked.add(affected[0]["dealId"])
            st.session_state["capital_automation_log"].insert(
                0, {"Hora": datetime.now().strftime("%H:%M:%S"), "Señal": sig, "Direccion": direction, "Resultado": result.get("dealStatus", "OK")}
            )
            st.success(f"Orden automatica enviada: {direction} {epic} — {sig}")
            st.rerun()
        except Exception as exc:
            st.session_state["capital_automation_log"].insert(
                0, {"Hora": datetime.now().strftime("%H:%M:%S"), "Señal": sig, "Direccion": direction, "Resultado": f"ERROR: {exc}"}
            )
            st.error(f"Motor automatico: {_order_error_message(exc)}")

    run_auto_engine()

if st.session_state["capital_automation_log"]:
    st.markdown("##### 📜 Log de automatizacion")
    st.dataframe(pd.DataFrame(st.session_state["capital_automation_log"]), width="stretch", hide_index=True)
