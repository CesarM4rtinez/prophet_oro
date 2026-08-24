"""Deteccion de estructura de mercado (swings, BOS) y confirmacion multi-temporalidad
5m/15m/1h — porteo directo de la celda 17 del notebook."""
from __future__ import annotations

import pandas as pd

from . import config


def detect_swings(df: pd.DataFrame, lookback: int = config.SWING_LOOKBACK) -> pd.DataFrame:
    df = df.copy()
    window = 2 * lookback + 1
    roll_max = df["high"].rolling(window, center=True).max()
    roll_min = df["low"].rolling(window, center=True).min()
    df["swing_high"] = df["high"] == roll_max
    df["swing_low"] = df["low"] == roll_min
    return df


def detect_structure(df: pd.DataFrame) -> tuple[pd.DataFrame, str | None]:
    """Quiebres de estructura (BOS): el cierre supera el ultimo swing high (alcista) o
    perfora el ultimo swing low (bajista). Devuelve cada quiebre y la tendencia vigente
    tras el ultimo quiebre detectado."""
    ultimo_sh = ultimo_sl = None
    quiebres = []
    tendencia = None
    idx_list = df.index
    highs, lows = df["high"].values, df["low"].values
    closes = df["close"].values
    sh_flags, sl_flags = df["swing_high"].values, df["swing_low"].values

    for i in range(len(df)):
        if sh_flags[i]:
            ultimo_sh = (i, highs[i])
        if sl_flags[i]:
            ultimo_sl = (i, lows[i])

        if ultimo_sh is not None and closes[i] > ultimo_sh[1] and i > ultimo_sh[0]:
            quiebres.append({"idx_break": i, "tiempo_break": idx_list[i], "tipo": "alcista"})
            ultimo_sh = None
            tendencia = "alcista"
        elif ultimo_sl is not None and closes[i] < ultimo_sl[1] and i > ultimo_sl[0]:
            quiebres.append({"idx_break": i, "tiempo_break": idx_list[i], "tipo": "bajista"})
            ultimo_sl = None
            tendencia = "bajista"

    return pd.DataFrame(quiebres), tendencia


def _liquidity_target(df_swings: pd.DataFrame, tipo: str, precio_actual: float, distancia_min_pct: float = 0.15):
    """Siguiente swing point no barrido en la direccion de la señal, exigiendo que este
    al menos `distancia_min_pct`% mas alla de la entrada (evita un TP casi pegado al
    precio actual por un micro-swing de ruido)."""
    distancia_min = precio_actual * distancia_min_pct / 100
    if tipo == "alcista":
        candidatos = df_swings.loc[df_swings["swing_high"] & (df_swings["high"] > precio_actual + distancia_min), "high"]
        return candidatos.min() if not candidatos.empty else None
    candidatos = df_swings.loc[df_swings["swing_low"] & (df_swings["low"] < precio_actual - distancia_min), "low"]
    return candidatos.max() if not candidatos.empty else None


def levels_for_timeframe(df_tf: pd.DataFrame, tendencia_tf: str | None) -> dict | None:
    """Entrada/SL/TP propios de UNA temporalidad, segun SU PROPIA tendencia vigente."""
    if tendencia_tf is None:
        return None
    precio = float(df_tf["close"].iloc[-1])
    tp = _liquidity_target(df_tf, tendencia_tf, precio)
    sl = float(df_tf["low"].tail(20).min()) if tendencia_tf == "alcista" else float(df_tf["high"].tail(20).max())
    return {"entrada": precio, "stop_loss": sl, "take_profit": tp, "tipo": tendencia_tf}


def _tendencia_en_momento(quiebres_ref: pd.DataFrame, momentos: pd.Series):
    tabla = quiebres_ref[["tiempo_break", "tipo"]].rename(columns={"tiempo_break": "tiempo", "tipo": "tendencia"})
    momentos_df = pd.DataFrame({"tiempo": momentos.reset_index(drop=True)})
    fusion = pd.merge_asof(momentos_df, tabla, on="tiempo", direction="backward")
    return fusion["tendencia"].values


def analyze_multi_timeframe(dfs: dict[str, pd.DataFrame]) -> dict:
    """dfs: {"5m": df, "15m": df, "1h": df}, ya con `detect_swings` aplicado. Replica la
    celda 17: confirmacion cruzada de BOS de 15m con 5m/1h, tasa historica de
    continuacion por numero de confirmaciones, niveles propios por temporalidad y
    veredicto final (señal operable solo si las 3 TF coinciden)."""
    df_5m, df_15m, df_1h = dfs["5m"], dfs["15m"], dfs["1h"]

    quiebres_5m, tendencia_5m = detect_structure(df_5m)
    quiebres_15m, tendencia_15m = detect_structure(df_15m)
    quiebres_1h, tendencia_1h = detect_structure(df_1h)

    tasa_continuacion: pd.Series = pd.Series(dtype=float)
    muestras_por_confirmacion: pd.Series = pd.Series(dtype=int)

    if not quiebres_15m.empty:
        quiebres_15m = quiebres_15m.copy()
        quiebres_15m["tend_5m"] = (
            _tendencia_en_momento(quiebres_5m, quiebres_15m["tiempo_break"]) if not quiebres_5m.empty else None
        )
        quiebres_15m["tend_1h"] = (
            _tendencia_en_momento(quiebres_1h, quiebres_15m["tiempo_break"]) if not quiebres_1h.empty else None
        )
        quiebres_15m["confirmaciones"] = (
            (quiebres_15m["tend_5m"] == quiebres_15m["tipo"]).astype(int)
            + (quiebres_15m["tend_1h"] == quiebres_15m["tipo"]).astype(int)
        )

        closes_15m = df_15m["close"].values
        n_15m = len(df_15m)
        umbral = config.STRUCTURE_CONTINUATION_THRESHOLD_PCT / 100
        resultados = []
        for row in quiebres_15m.itertuples():
            precio_break = closes_15m[row.idx_break]
            if row.tipo == "alcista":
                objetivo, invalidacion = precio_break * (1 + umbral), precio_break * (1 - umbral)
            else:
                objetivo, invalidacion = precio_break * (1 - umbral), precio_break * (1 + umbral)
            resultado = "sin_definir"
            fin = min(n_15m, row.idx_break + 1 + config.STRUCTURE_RESULT_WINDOW)
            for j in range(row.idx_break + 1, fin):
                precio = closes_15m[j]
                if row.tipo == "alcista":
                    if precio <= invalidacion:
                        resultado = "fallo"
                        break
                    if precio >= objetivo:
                        resultado = "continuo"
                        break
                else:
                    if precio >= invalidacion:
                        resultado = "fallo"
                        break
                    if precio <= objetivo:
                        resultado = "continuo"
                        break
            resultados.append(resultado)
        quiebres_15m["resultado"] = resultados

        evaluados = quiebres_15m[quiebres_15m["resultado"].isin(["continuo", "fallo"])]
        if not evaluados.empty:
            tasa_continuacion = evaluados.groupby("confirmaciones")["resultado"].apply(
                lambda s: round((s == "continuo").mean() * 100, 1)
            )
            muestras_por_confirmacion = evaluados.groupby("confirmaciones").size()

    direcciones = {"5m": tendencia_5m, "15m": tendencia_15m, "1h": tendencia_1h}
    dfs_tf = {"5m": df_5m, "15m": df_15m, "1h": df_1h}
    niveles_tf = {tf: levels_for_timeframe(dfs_tf[tf], direcciones[tf]) for tf in direcciones}

    alineadas_alcista = sum(1 for d in direcciones.values() if d == "alcista")
    alineadas_bajista = sum(1 for d in direcciones.values() if d == "bajista")
    if alineadas_alcista == 3:
        veredicto = "alcista"
    elif alineadas_bajista == 3:
        veredicto = "bajista"
    else:
        veredicto = None

    return {
        "direcciones": direcciones,
        "niveles": niveles_tf,
        "veredicto": veredicto,
        "tasa_continuacion": tasa_continuacion,
        "muestras_por_confirmacion": muestras_por_confirmacion,
        "dfs": dfs_tf,
    }
