"""Rango del dia anterior (PDH/PDL), killzones por sesion y rangos historicos.

Todo se expresa en hora de El Salvador (UTC-6, sin horario de verano). Las
killzones se definen en hora de Nueva York y se convierten, asi se mueven solas
cuando NY cambia de horario.

Dia de trading (D1): de 16:00 a 16:00 hora de El Salvador (17:00 NY en
invierno, el corte de CME). Las sesiones con etiqueta sabado o domingo se
descartan: PAXG-USD cotiza 24/7, pero el oro real no.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time

import numpy as np
import pandas as pd

from .daily_levels import LOCAL_TZ

NY_TZ = "America/New_York"
SESSION_SHIFT = pd.Timedelta(hours=8)  # 16:00 local -> 00:00 del dia de la sesion

# (nombre, inicio NY, fin NY, el inicio cae en el dia calendario anterior)
KILLZONES_NY = (
    ("Asia", time(20, 0), time(0, 0), True),
    ("Londres", time(2, 0), time(5, 0), False),
    ("Nueva York", time(7, 0), time(10, 0), False),
)


@dataclass(frozen=True)
class Killzone:
    name: str
    start: pd.Timestamp
    end: pd.Timestamp


def to_local(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    idx = pd.to_datetime(out.index)
    idx = idx.tz_localize("UTC") if idx.tz is None else idx
    out.index = idx.tz_convert(LOCAL_TZ)
    return out.sort_index()


def session_dates(index: pd.DatetimeIndex) -> np.ndarray:
    return np.array((index + SESSION_SHIFT).date)


def trading_sessions(df_local: pd.DataFrame) -> dict[date, pd.DataFrame]:
    labels = session_dates(df_local.index)
    out = {}
    for d, g in df_local.groupby(labels):
        if pd.Timestamp(d).dayofweek < 5:
            out[d] = g
    return out


def session_bounds(day: date) -> tuple[pd.Timestamp, pd.Timestamp]:
    end = pd.Timestamp(datetime.combine(day, time(16, 0)), tz=LOCAL_TZ)
    return end - pd.Timedelta(hours=24), end


def killzones_for(day: date) -> list[Killzone]:
    zones = []
    for name, start_ny, end_ny, starts_prev_day in KILLZONES_NY:
        start_day = pd.Timestamp(day) - pd.Timedelta(days=1 if starts_prev_day else 0)
        start = pd.Timestamp(datetime.combine(start_day.date(), start_ny), tz=NY_TZ)
        end_day = start_day if end_ny > start_ny else start_day + pd.Timedelta(days=1)
        end = pd.Timestamp(datetime.combine(end_day.date(), end_ny), tz=NY_TZ)
        zones.append(Killzone(name, start.tz_convert(LOCAL_TZ), end.tz_convert(LOCAL_TZ)))
    return zones


def killzone_summary(session: pd.DataFrame, zones: list[Killzone], pdh: float, pdl: float,
                     now: pd.Timestamp) -> pd.DataFrame:
    rows = []
    for z in zones:
        k = session[(session.index >= z.start) & (session.index < z.end)]
        if now < z.start or k.empty:
            estado = "Por venir"
        elif now < z.end:
            estado = "En curso"
        else:
            estado = "Terminada"
        rows.append({
            "Killzone": z.name,
            "Inicio": z.start.strftime("%H:%M"),
            "Fin": z.end.strftime("%H:%M"),
            "Estado": estado,
            "Máximo": float(k["high"].max()) if len(k) else np.nan,
            "Mínimo": float(k["low"].min()) if len(k) else np.nan,
            "Cierre": float(k["close"].iloc[-1]) if len(k) else np.nan,
            "Barrió PDH": bool(len(k) and k["high"].max() > pdh),
            "Barrió PDL": bool(len(k) and k["low"].min() < pdl),
        })
    return pd.DataFrame(rows)


def killzone_history(df_local: pd.DataFrame) -> pd.DataFrame:
    """Por cada sesion y killzone: si barrio PDH/PDL y si cerro de vuelta dentro."""
    sessions = trading_sessions(df_local)
    days = sorted(sessions)
    rows = []
    for prev, cur in zip(days, days[1:]):
        p = sessions[prev]
        if len(p) < 150:
            continue
        pdh, pdl = float(p["high"].max()), float(p["low"].min())
        for z in killzones_for(cur):
            k = sessions[cur]
            k = k[(k.index >= z.start) & (k.index < z.end)]
            if len(k) < 20:
                continue
            close = float(k["close"].iloc[-1])
            sh, sl = k["high"].max() > pdh, k["low"].min() < pdl
            rows.append({"dia": cur, "kz": z.name, "barre_pdh": bool(sh), "barre_pdl": bool(sl),
                         "vuelve_pdh": bool(sh and close < pdh), "vuelve_pdl": bool(sl and close > pdl)})
    return pd.DataFrame(rows)


def range_bands(df_1h_local: pd.DataFrame, now: pd.Timestamp, last_price: float,
                targets: list[pd.Timestamp]) -> pd.DataFrame:
    """Rango 95 % / 99 % del precio desde ahora hasta cada hora objetivo.

    Usa, en cada sesion pasada, el cambio entre la vela de la misma hora de la
    sesion que ahora y el cierre de la vela que termina en la hora objetivo.
    Se escala por la volatilidad diaria de 20 dias contra la de toda la muestra.
    """
    df = df_1h_local[df_1h_local.index.minute == 0]
    sessions = trading_sessions(df)
    start_off = int(((now.floor("h") + SESSION_SHIFT) - (now.floor("h") + SESSION_SHIFT).normalize()) / pd.Timedelta(hours=1))
    closes = pd.Series({d: float(g["close"].iloc[-1]) for d, g in sessions.items()})
    rets = np.log(closes / closes.shift()).dropna()
    scale = float(rets.iloc[-20:].std() / rets.std()) if len(rets) > 40 else 1.0

    rows = []
    for t in targets:
        if t <= now:
            continue
        end_off = int(((t + SESSION_SHIFT) - (t + SESSION_SHIFT).normalize()) / pd.Timedelta(hours=1)) or 24
        moves = []
        for g in sessions.values():
            off = ((g.index + SESSION_SHIFT) - (g.index + SESSION_SHIFT).normalize()) / pd.Timedelta(hours=1)
            off = np.asarray(off).astype(int)
            a, b = g[off == start_off], g[off == end_off - 1]
            if len(a) and len(b):
                moves.append(float(b["close"].iloc[0]) / float(a["open"].iloc[0]) - 1)
        if len(moves) < 30:
            continue
        m = np.array(moves) * scale
        q = np.percentile(m, [0.5, 2.5, 97.5, 99.5])
        rows.append({"hasta": t, "n": len(moves), "lo99": last_price * (1 + q[0]),
                     "lo95": last_price * (1 + q[1]), "hi95": last_price * (1 + q[2]),
                     "hi99": last_price * (1 + q[3])})
    return pd.DataFrame(rows)
