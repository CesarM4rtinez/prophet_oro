"""Carga y filtrado del calendario economico FTMO, compartido por las celdas 10 y 12
del notebook (probabilidad 1D + calendario, y plan de trading killzone NY)."""
from __future__ import annotations

import pandas as pd

from . import config

IMPACTO_LABEL = {0: "Bajo", 1: "Medio", 2: "Alto"}
IMPACTO_COLOR = {0: "gray", 1: "orange", 2: "red"}


def load_relevant_events(symbol_label: str = config.SYMBOL_LABEL) -> pd.DataFrame:
    """Eventos del calendario relevantes para el activo (USD/XAU mueven directamente
    su precio); columna 'Impacto' ya mapeada desde 'Restricciones' (0/1/2). 'Fechas'
    queda tz-aware (el excel guarda offsets fijos, ej. -06:00)."""
    if not config.CALENDAR_PATH.exists():
        return pd.DataFrame(columns=["Fechas", "Instrumento", "Descripción", "Restricciones", "Impacto"])
    calendario = pd.read_excel(config.CALENDAR_PATH)
    calendario["Fechas"] = pd.to_datetime(calendario["Fechas"])
    es_relevante = calendario["Instrumento"].str.contains("USD|XAU", case=False, na=False)
    calendario_activo = calendario.loc[es_relevante].sort_values("Fechas").reset_index(drop=True)
    calendario_activo["Impacto"] = calendario_activo["Restricciones"].map(IMPACTO_LABEL)
    return calendario_activo


def events_naive(symbol_label: str = config.SYMBOL_LABEL) -> pd.DataFrame:
    """Version con 'Fechas' sin timezone (celda 10), para cruzar con velas cuyo index
    ya viene naive."""
    df = load_relevant_events(symbol_label)
    if df.empty:
        return df
    df = df.copy()
    if df["Fechas"].dt.tz is not None:
        df["Fechas"] = df["Fechas"].dt.tz_localize(None)
    return df


def events_in_timezone(tz: str, symbol_label: str = config.SYMBOL_LABEL) -> pd.DataFrame:
    """Version con 'Fechas' convertida a `tz` (celda 12, killzone de Nueva York)."""
    df = load_relevant_events(symbol_label)
    if df.empty:
        return df
    df = df.copy()
    if df["Fechas"].dt.tz is None:
        df["Fechas"] = df["Fechas"].dt.tz_localize("UTC")
    df["Fechas"] = df["Fechas"].dt.tz_convert(tz)
    return df
