"""Utilidades de tiempo/sesion compartidas por las paginas del dashboard."""
from __future__ import annotations

from datetime import datetime

import pandas as pd

from . import config


def current_session_label(timestamp=None) -> str:
    """Nombre de la sesion de mayor liquidez vigente en `timestamp` (o ahora mismo en
    UTC si no se especifica): "Londres", "Nueva York" o "Fuera de sesion"."""
    ts = pd.Timestamp(timestamp) if timestamp is not None else pd.Timestamp.now(tz="UTC")
    hour = ts.tz_convert("UTC").hour if ts.tzinfo is not None else ts.hour
    london_start, london_end = config.SESSION_LONDON_UTC
    ny_start, ny_end = config.SESSION_NEWYORK_UTC
    if london_start <= hour < london_end:
        return "Londres"
    if ny_start <= hour < ny_end:
        return "Nueva York"
    return "Fuera de sesion"


def to_new_york_time(timestamp) -> datetime:
    """Convierte un timestamp (naive -> se asume UTC; tz-aware -> se convierte) a la
    hora de Nueva York usada en todo el dashboard (UTC-4 fijo, no ajusta por horario
    de invierno EST/UTC-5)."""
    ts = pd.Timestamp(timestamp)
    ts_utc = ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")
    ny = ts_utc + pd.Timedelta(hours=config.NY_UTC_OFFSET_HOURS)
    return ny.to_pydatetime().replace(tzinfo=None)
