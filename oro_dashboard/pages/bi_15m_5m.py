import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import matplotlib.pyplot as plt
import pandas as pd
import streamlit as st

from core import config
from core.data import fetch_interval
from core.mtf_signal import mtf_15m_5m_signal
from core.state import render_refresh_control
from core.timeutil import current_session_label, to_new_york_time
from ui.mpl_charts import mtf_zone_chart
from ui.theme import inject_css, render_data_status, render_kpi_tile, render_rule_card, render_signal_pill

inject_css()

st.title("📊 Panel BI — Dirección 15m / Entrada 5m")
st.caption(
    "Panel de business intelligence con una regla de confluencia de DOS temporalidades "
    "(deliberadamente mas simple que la cascada de 3 temporalidades de la Estrategia "
    "Institucional SMC): la **dirección** se define en 15 minutos exigiendo una "
    "**continuación de estructura** (BOS), y la **entrada** se dispara en 5 minutos ante "
    "cualquier **quiebre de estructura** (BOS o CHoCH) alineado con esa dirección."
)

refresh_seconds = render_refresh_control()

_BIAS_ARROW = {"alcista": "↑", "bajista": "↓"}
_TIPO_LABEL = {"BOS": "BOS · continuación", "CHoCH": "CHoCH · cambio de estructura"}


def _quiebres_table(df: pd.DataFrame, quiebres: list[dict]) -> pd.DataFrame:
    rows = [
        {
            "Hora": df.index[q["idx"]],
            "Nivel": q["level"],
            "Dirección": q["kind"].capitalize(),
            "Tipo": _TIPO_LABEL[q["tipo"]],
        }
        for q in reversed(quiebres[-15:])
    ]
    return pd.DataFrame(rows)


@st.fragment(run_every=refresh_seconds or None)
def render() -> None:
    df_direction = fetch_interval(config.BI_DIRECTION_INTERVAL)
    df_entry = fetch_interval(config.BI_ENTRY_INTERVAL)

    if df_direction.empty or df_entry.empty or len(df_direction) < 60 or len(df_entry) < 60:
        st.warning(
            f"No hay suficientes velas en {config.BI_DIRECTION_INTERVAL}/{config.BI_ENTRY_INTERVAL} ahora mismo."
        )
        return

    result = mtf_15m_5m_signal(df_direction, df_entry)
    render_data_status(to_new_york_time(df_entry.index[-1]), current_session_label(df_entry.index[-1]))

    trend_dir = result["trend_dir"]
    signal = result["signal"]
    preview = result["preview"]

    # --- KPIs -------------------------------------------------------------
    dir_label = f"{_BIAS_ARROW.get(trend_dir, '→')} {trend_dir.capitalize()}" if trend_dir else "Sin datos"
    cont_label = "✅ Confirmada (BOS)" if result["direction_confirmed"] else "⚠️ Sin confirmar (CHoCH)"
    last_break_entry = result["last_break_entry"]
    if last_break_entry is None:
        entry_break_label = "Sin quiebres"
    else:
        entry_break_label = f"{_BIAS_ARROW.get(last_break_entry['kind'], '')} {last_break_entry['tipo']}"
    if signal:
        signal_kpi = f"🟢 {signal['direction']}" if signal["direction"] == "BUY" else f"🔴 {signal['direction']}"
    else:
        signal_kpi = "⏳ Esperar"
    rr_label = f"1:{signal['rr']:.1f}" if signal and signal["rr"] else "—"

    kpis_html = "".join(
        [
            render_kpi_tile(f"Dirección ({config.BI_DIRECTION_INTERVAL})", dir_label, accent="#3987e5"),
            render_kpi_tile(
                "Continuación 15m", cont_label,
                accent="#0ca30c" if result["direction_confirmed"] else "#fab219",
            ),
            render_kpi_tile(
                f"Último quiebre ({config.BI_ENTRY_INTERVAL})", entry_break_label,
                delta="Reciente" if result["entry_recent"] else "Antiguo / fuera de ventana",
                accent="#199e70" if result["entry_recent"] else "#898781",
            ),
            render_kpi_tile(
                "Señal", signal_kpi,
                accent="#0ca30c" if (signal and signal["direction"] == "BUY") else
                       "#d03b3b" if (signal and signal["direction"] == "SELL") else "#fab219",
            ),
            render_kpi_tile("Precio actual", f"${result['current_price']:,.2f}", accent="#c98500"),
            render_kpi_tile("RR estimado", rr_label, accent="#9085e9"),
        ]
    )
    st.markdown(f'<div class="oro-kpi-grid">{kpis_html}</div>', unsafe_allow_html=True)

    # --- Señal / explicación ------------------------------------------------
    if signal:
        pill = render_signal_pill("buy" if signal["direction"] == "BUY" else "sell", f"{signal['direction']} — señal activa")
        st.markdown(pill, unsafe_allow_html=True)
        st.markdown(
            f"**Entrada:** ${signal['entry']:,.2f} &nbsp;·&nbsp; **SL:** ${signal['sl']:,.2f} "
            f"&nbsp;·&nbsp; **TP:** ${signal['tp']:,.2f} &nbsp;·&nbsp; **RR:** 1:{signal['rr']:.2f}"
        )
        st.caption(
            f"Disparador: quiebre {signal['trigger']['tipo']} en {config.BI_ENTRY_INTERVAL} "
            f"a ${signal['trigger']['level']:,.2f}, alineado con la continuación de estructura "
            f"vigente en {config.BI_DIRECTION_INTERVAL}. SL apoyado en ese mismo nivel (con colchón "
            f"ATR), TP en la liquidez no barrida mas cercana de {config.BI_DIRECTION_INTERVAL}."
        )
    else:
        st.markdown(render_signal_pill("wait", "Esperar — reglas incompletas"), unsafe_allow_html=True)
        motivos = []
        if trend_dir is None:
            motivos.append(f"aún no hay una tendencia definida en {config.BI_DIRECTION_INTERVAL}")
        elif not result["direction_confirmed"]:
            motivos.append(
                f"el último quiebre en {config.BI_DIRECTION_INTERVAL} fue un CHoCH (cambio de estructura), "
                "todavía no un BOS que confirme continuación"
            )
        if trend_dir is not None and not result["entry_recent"]:
            motivos.append(f"no hay un quiebre reciente de estructura en {config.BI_ENTRY_INTERVAL}")
        elif trend_dir is not None and not result["entry_aligned"]:
            motivos.append(f"el último quiebre de {config.BI_ENTRY_INTERVAL} va en contra de la dirección de {config.BI_DIRECTION_INTERVAL}")
        if not motivos:
            motivos.append("el RR resultante no queda del lado correcto del precio")
        st.caption("Falta: " + "; ".join(motivos) + ".")
        if preview:
            st.caption(
                f"📐 Vista previa en el gráfico de entrada: posición {'LARGA' if preview['direction'] == 'BUY' else 'CORTA'} "
                f"proyectada (zonas mas tenues, borde discontinuo) usando el quiebre {preview['trigger']['tipo']} "
                f"mas reciente de {config.BI_ENTRY_INTERVAL} a favor de {config.BI_DIRECTION_INTERVAL} — todavia no es una señal, "
                "es solo una referencia de cómo se vería."
            )

    # --- Reglas de la metodologia -------------------------------------------
    st.markdown("##### Reglas de la metodología")
    rules_html = "".join(
        [
            render_rule_card(1, f"Dirección en {config.BI_DIRECTION_INTERVAL}", "La temporalidad de dirección/sesgo macro de la señal.", "done"),
            render_rule_card(2, f"Entrada en {config.BI_ENTRY_INTERVAL}", "La temporalidad donde se dispara el gatillo de entrada.", "done"),
            render_rule_card(
                3, f"Quiebre de estructura en {config.BI_ENTRY_INTERVAL}",
                "Se busca cualquier quiebre (BOS o CHoCH) reciente en la temporalidad de entrada.",
                "done" if result["entry_recent"] else "pending",
            ),
            render_rule_card(
                4, f"Continuación de estructura en {config.BI_DIRECTION_INTERVAL}",
                "Se exige que el último quiebre en la temporalidad de dirección sea un BOS (a favor de la tendencia vigente).",
                "done" if result["direction_confirmed"] else "pending",
            ),
        ]
    )
    st.markdown(f'<div class="oro-rule-grid">{rules_html}</div>', unsafe_allow_html=True)

    # --- Grafico direccion (15m) --------------------------------------------
    st.markdown("---")
    st.markdown(f"#### Dirección — continuación de estructura ({config.BI_DIRECTION_INTERVAL})")
    fig_dir = mtf_zone_chart(
        df_direction, result["swings_dir"], result["breaks_dir"], trend_dir,
        config.SYMBOL_LABEL, config.BI_DIRECTION_INTERVAL, "Dirección",
        max_zones=6, window=200,
    )
    st.pyplot(fig_dir, width="stretch")
    plt.close(fig_dir)

    if result["breaks_dir"]:
        st.dataframe(_quiebres_table(df_direction, result["breaks_dir"]), width="stretch", hide_index=True)
    st.caption("Zonas: quiebre BOS (continuación, borde discontinuo) · quiebre CHoCH (cambio de estructura, borde solido y mas opaco).")

    # --- Grafico entrada (5m) ------------------------------------------------
    st.markdown("---")
    st.markdown(f"#### Entrada — quiebre de estructura ({config.BI_ENTRY_INTERVAL})")
    fig_entry = mtf_zone_chart(
        df_entry, result["swings_entry"], result["breaks_entry"], trend_dir,
        config.SYMBOL_LABEL, config.BI_ENTRY_INTERVAL, "Entrada",
        position=(signal or preview), position_confirmed=bool(signal),
        max_zones=5, window=150,
    )
    st.pyplot(fig_entry, width="stretch")
    plt.close(fig_entry)

    if result["breaks_entry"]:
        st.dataframe(_quiebres_table(df_entry, result["breaks_entry"]), width="stretch", hide_index=True)
    st.caption(
        "Posición LARGA (verde) o CORTA (roja): zona de beneficio (entrada→TP) y zona de riesgo "
        "(entrada→SL), proyectadas hacia adelante desde el quiebre disparador. Trazo solido = señal "
        "confirmada (4 reglas) · trazo discontinuo = vista previa (dirección definida pero sin confirmar)."
    )


render()

st.markdown("---")
st.caption(
    "Metodología basada en conceptos estándar de estructura de mercado (BOS/CHoCH) y análisis "
    "multi-temporalidad: QuantConnect Docs, ChartSchool (StockCharts), School of Pipsology "
    "(BabyPips) y CME Group Education. No replica ningún algoritmo propietario ni constituye "
    "asesoría financiera — es una aproximación educativa/estadística sobre datos públicos de "
    f"{config.SYMBOL} (proxy de {config.SYMBOL_LABEL})."
)
