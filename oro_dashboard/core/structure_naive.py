"""Tendencia y niveles PROPIOS de cada temporalidad (ultimo quiebre de estructura +
liquidez mas cercana en esa direccion) — misma logica que la celda "Estructura
Multi-Temporalidad" de proyecciones_oro.ipynb: la tendencia es simplemente la
direccion del ULTIMO BOS detectado, y el TP es el swing no barrido mas cercano por
ENCIMA del precio actual (alcista) o por DEBAJO (bajista) — así el TP siempre queda
del lado correcto del precio actual, a diferencia de tomar el TP "de fabrica" de una
zona historica (que puede haber quedado obsoleto si el precio ya lo supero).

Deliberadamente separado de `core.smc_zones` (motor "maduro" con retest + AMD,
usado en pages/structure_mtf.py para las señales operables reales): aqui no hay
confirmacion de manipulacion ni de retest, asi que esto NUNCA debe usarse como señal
de entrada — solo para el panorama comparativo "que dice cada temporalidad por su
cuenta" del grafico Estructura Multi-Temporalidad."""
from __future__ import annotations

import pandas as pd

from .smc_zones import detect_swings

SWING_LOOKBACK = 3


def own_trend(df: pd.DataFrame, lookback: int = SWING_LOOKBACK) -> tuple[pd.DataFrame, str | None]:
    """(df_con_swings, tendencia): tendencia es la direccion del ULTIMO quiebre de
    estructura (cierre que supera el ultimo swing high/low vigente) en toda la
    serie, o None si no hubo ninguno todavia."""
    swings = detect_swings(df, lookback=lookback)
    highs, lows, closes = df["high"].to_numpy(), df["low"].to_numpy(), df["close"].to_numpy()
    sh_flags, sl_flags = swings["swing_high"].to_numpy(), swings["swing_low"].to_numpy()

    ultimo_sh = ultimo_sl = None
    tendencia: str | None = None
    for i in range(len(df)):
        if sh_flags[i]:
            ultimo_sh = (i, highs[i])
        if sl_flags[i]:
            ultimo_sl = (i, lows[i])

        if ultimo_sh is not None and i > ultimo_sh[0] and closes[i] > ultimo_sh[1]:
            ultimo_sh = None
            tendencia = "alcista"
        elif ultimo_sl is not None and i > ultimo_sl[0] and closes[i] < ultimo_sl[1]:
            ultimo_sl = None
            tendencia = "bajista"

    return swings, tendencia


def nearest_liquidity_target(
    df_swings: pd.DataFrame, tendencia: str, precio_actual: float, distancia_min_pct: float = 0.15
) -> float | None:
    """Swing no barrido mas cercano en la direccion de `tendencia`, exigiendo que
    este al menos `distancia_min_pct`% mas alla del precio actual — sin este filtro
    un micro-swing casi pegado al precio actual podria quedar como "el mas cercano"
    con recompensa casi nula frente al riesgo del SL."""
    distancia_min = precio_actual * distancia_min_pct / 100
    if tendencia == "alcista":
        candidatos = df_swings.loc[df_swings["swing_high"] & (df_swings["high"] > precio_actual + distancia_min), "high"]
        return float(candidatos.min()) if not candidatos.empty else None
    candidatos = df_swings.loc[df_swings["swing_low"] & (df_swings["low"] < precio_actual - distancia_min), "low"]
    return float(candidatos.max()) if not candidatos.empty else None
