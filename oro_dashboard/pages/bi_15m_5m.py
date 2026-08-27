import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import matplotlib.pyplot as plt
import pandas as pd
import streamlit as st

from core import config
from core.data import fetch_interval
from core.mtf_signal import mtf_direction_entry_signal
from core.state import render_refresh_control
from core.timeutil import current_session_label, to_new_york_time
from ui.mpl_charts import mtf_zone_chart
from ui.theme import COLORS, inject_css, render_data_status, render_kpi_tile, render_rule_card, render_signal_pill

inject_css()

st.title("📊 Panel BI — Multi-Timeframe")
st.caption(
    "Panel de business intelligence con dos cascadas de confluencia de DOS temporalidades "
    "(deliberadamente mas simples que la cascada de 3 temporalidades de la Estrategia "
    "Institucional SMC), la misma regla en dos escalas para poder compararlas: la "
    "**dirección** se define en la temporalidad superior exigiendo una **continuación de "
    "estructura** (BOS), y la **entrada** se dispara en la temporalidad inferior ante "
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


def _cascade_status_text(result: dict) -> tuple[str, str]:
    """(direccion_html, señal_html) para la tarjeta de comparativa."""
    trend_dir = result["trend_dir"]
    dir_txt = f"{_BIAS_ARROW.get(trend_dir, '→')} {trend_dir.capitalize()}" if trend_dir else "Sin datos"
    if result["signal"]:
        sig = result["signal"]
        icon = "🟢" if sig["direction"] == "BUY" else "🔴"
        sig_txt = f"{icon} {sig['direction']} · RR 1:{sig['rr']:.1f}"
    elif result["preview"]:
        pv = result["preview"]
        sig_txt = f"👁 Vista previa: {'LARGO' if pv['direction'] == 'BUY' else 'CORTO'}"
    else:
        sig_txt = "⏳ Esperar"
    return dir_txt, sig_txt


def _cascade_summary_card(label: str, result: dict | None) -> str:
    if result is None:
        body = f'<p style="color:{COLORS["text_muted"]}; font-size:.8rem; margin:0;">Sin datos suficientes ahora mismo.</p>'
    else:
        dir_txt, sig_txt = _cascade_status_text(result)
        body = (
            f'<div style="font-size:.82rem; color:{COLORS["text_secondary"]}; line-height:1.9;">'
            f'Dirección: <b style="color:{COLORS["text_primary"]}">{dir_txt}</b><br>'
            f'Señal: <b style="color:{COLORS["text_primary"]}">{sig_txt}</b></div>'
        )
    return (
        f'<div class="oro-card" style="height:100%;">'
        f'<h4 style="margin:0 0 8px; font-size:.88rem; color:{COLORS["text_primary"]};">{label}</h4>{body}</div>'
    )


def _render_cascade_section(
    df_direction: pd.DataFrame, df_entry: pd.DataFrame, result: dict, direction_interval: str, entry_interval: str
) -> None:
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
            render_kpi_tile(f"Dirección ({direction_interval})", dir_label, accent="#3987e5"),
            render_kpi_tile(
                f"Continuación {direction_interval}", cont_label,
                accent="#0ca30c" if result["direction_confirmed"] else "#fab219",
            ),
            render_kpi_tile(
                f"Último quiebre ({entry_interval})", entry_break_label,
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
            f"Disparador: quiebre {signal['trigger']['tipo']} en {entry_interval} "
            f"a ${signal['trigger']['level']:,.2f}, alineado con la continuación de estructura "
            f"vigente en {direction_interval}. SL apoyado en ese mismo nivel (con colchón "
            f"ATR), TP en la liquidez no barrida mas cercana de {direction_interval}."
        )
    else:
        st.markdown(render_signal_pill("wait", "Esperar — reglas incompletas"), unsafe_allow_html=True)
        motivos = []
        if trend_dir is None:
            motivos.append(f"aún no hay una tendencia definida en {direction_interval}")
        elif not result["direction_confirmed"]:
            motivos.append(
                f"el último quiebre en {direction_interval} fue un CHoCH (cambio de estructura), "
                "todavía no un BOS que confirme continuación"
            )
        if trend_dir is not None and not result["entry_recent"]:
            motivos.append(f"no hay un quiebre reciente de estructura en {entry_interval}")
        elif trend_dir is not None and not result["entry_aligned"]:
            motivos.append(f"el último quiebre de {entry_interval} va en contra de la dirección de {direction_interval}")
        if not motivos:
            motivos.append("el RR resultante no queda del lado correcto del precio")
        st.caption("Falta: " + "; ".join(motivos) + ".")
        if preview:
            st.caption(
                f"📐 Vista previa en el gráfico de entrada: posición {'LARGA' if preview['direction'] == 'BUY' else 'CORTA'} "
                f"proyectada (zonas mas tenues, borde discontinuo) usando el quiebre {preview['trigger']['tipo']} "
                f"mas reciente de {entry_interval} a favor de {direction_interval} — todavia no es una señal, "
                "es solo una referencia de cómo se vería."
            )

    # --- Reglas de la metodologia -------------------------------------------
    st.markdown("##### Reglas de la metodología")
    rules_html = "".join(
        [
            render_rule_card(1, f"Dirección en {direction_interval}", "La temporalidad de dirección/sesgo macro de la señal.", "done"),
            render_rule_card(2, f"Entrada en {entry_interval}", "La temporalidad donde se dispara el gatillo de entrada.", "done"),
            render_rule_card(
                3, f"Quiebre de estructura en {entry_interval}",
                "Se busca cualquier quiebre (BOS o CHoCH) reciente en la temporalidad de entrada.",
                "done" if result["entry_recent"] else "pending",
            ),
            render_rule_card(
                4, f"Continuación de estructura en {direction_interval}",
                "Se exige que el último quiebre en la temporalidad de dirección sea un BOS (a favor de la tendencia vigente).",
                "done" if result["direction_confirmed"] else "pending",
            ),
        ]
    )
    st.markdown(f'<div class="oro-rule-grid">{rules_html}</div>', unsafe_allow_html=True)

    # --- Grafico direccion --------------------------------------------------
    st.markdown("---")
    st.markdown(f"#### Dirección — continuación de estructura ({direction_interval})")
    fig_dir = mtf_zone_chart(
        df_direction, result["swings_dir"], result["breaks_dir"], trend_dir,
        config.SYMBOL_LABEL, direction_interval, "Dirección",
        max_zones=6, window=200,
    )
    st.pyplot(fig_dir, width="stretch")
    plt.close(fig_dir)

    if result["breaks_dir"]:
        st.dataframe(_quiebres_table(df_direction, result["breaks_dir"]), width="stretch", hide_index=True)
    st.caption("Zonas: quiebre BOS (continuación, borde discontinuo) · quiebre CHoCH (cambio de estructura, borde solido y mas opaco).")

    # --- Grafico entrada ------------------------------------------------------
    st.markdown("---")
    st.markdown(f"#### Entrada — quiebre de estructura ({entry_interval})")
    fig_entry = mtf_zone_chart(
        df_entry, result["swings_entry"], result["breaks_entry"], trend_dir,
        config.SYMBOL_LABEL, entry_interval, "Entrada",
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


@st.fragment(run_every=refresh_seconds or None)
def render() -> None:
    intervals_needed = sorted({c["direction"] for c in config.BI_CASCADES} | {c["entry"] for c in config.BI_CASCADES})
    dfs = {label: fetch_interval(label) for label in intervals_needed}

    cascades = []
    for c in config.BI_CASCADES:
        df_direction, df_entry = dfs[c["direction"]], dfs[c["entry"]]
        ok = not df_direction.empty and not df_entry.empty and len(df_direction) >= 60 and len(df_entry) >= 60
        result = mtf_direction_entry_signal(df_direction, df_entry) if ok else None
        cascades.append({**c, "df_direction": df_direction, "df_entry": df_entry, "result": result, "ok": ok})

    if not any(c["ok"] for c in cascades):
        st.warning(f"No hay suficientes velas en {'/'.join(intervals_needed)} ahora mismo.")
        return

    freshest = dfs[config.BI_CASCADES[0]["entry"]]
    if not freshest.empty:
        render_data_status(to_new_york_time(freshest.index[-1]), current_session_label(freshest.index[-1]))

    # --- Comparativa entre cascadas -----------------------------------------
    st.markdown("### Comparativa entre cascadas")
    cols = st.columns(len(cascades))
    for col, c in zip(cols, cascades):
        col.markdown(_cascade_summary_card(f"Cascada {c['label']}", c["result"]), unsafe_allow_html=True)

    trends = [c["result"]["trend_dir"] for c in cascades if c["ok"] and c["result"]["trend_dir"] is not None]
    if len(trends) == len(cascades) and len(cascades) > 1:
        if len(set(trends)) == 1:
            st.success(f"✅ Las cascadas coinciden en dirección **{trends[0]}** — mayor confianza en el sesgo.")
        else:
            detalle = " vs. ".join(f"{c['label']}: {c['result']['trend_dir']}" for c in cascades if c["ok"])
            st.warning(f"⚠️ Las cascadas discrepan en dirección ({detalle}) — evitar operar hasta que se alineen.")
    elif len(cascades) > 1:
        st.caption("Todavía no hay tendencia definida en alguna de las cascadas para comparar.")

    # --- Secciones por cascada ------------------------------------------------
    for c in cascades:
        st.markdown("---")
        st.markdown(f"## Cascada {c['label']}")
        if not c["ok"]:
            st.warning(f"No hay suficientes velas en {c['direction']}/{c['entry']} ahora mismo.")
            continue
        _render_cascade_section(c["df_direction"], c["df_entry"], c["result"], c["direction"], c["entry"])


render()

st.markdown("---")
st.caption(
    "Metodología basada en conceptos estándar de estructura de mercado (BOS/CHoCH) y análisis "
    "multi-temporalidad: QuantConnect Docs, ChartSchool (StockCharts), School of Pipsology "
    "(BabyPips) y CME Group Education. No replica ningún algoritmo propietario ni constituye "
    "asesoría financiera — es una aproximación educativa/estadística sobre datos públicos de "
    f"{config.SYMBOL} (proxy de {config.SYMBOL_LABEL})."
)
