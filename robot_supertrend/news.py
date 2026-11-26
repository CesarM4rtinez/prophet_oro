"""Filtro fundamental: no abrir ni agregar posiciones alrededor de noticias de alto impacto.

Por que es un FILTRO y no una señal de direccion: el resultado de un dato (CPI, empleo,
PCE, decision de la Fed) no se conoce antes de publicarse, y la reaccion del oro en los
primeros minutos es la mas violenta y la mas propensa a revertir (el 25/11 el PCE tiro
el oro −$90 y en 4 horas rebotó +$119). La forma robusta de "no ir en contra de una
noticia" es: no entrar justo antes ni justo despues, y dejar que el Supertrend de 1h,
calculado sobre velas cerradas, refleje la direccion que el mercado eligio. Siguiendo
la regla de trader-news ("los titulares son pistas, no hechos; nada de predicciones"),
los titulares no deciden compras ni ventas.

Fuentes:
1. Calendario economico semanal de Forex Factory (JSON publico de faireconomy.media):
   agenda de los organismos oficiales (BLS, BEA, Reserva Federal, Tesoro, Census,
   ISM...) con nivel de impacto. Se usan los eventos de USD (los que mueven al oro).
2. Si el calendario no se puede descargar, el filtro FALLA HACIA LO SEGURO: bloquea
   nuevas entradas en las ventanas habituales de publicacion de EE. UU. (08:30, 10:00 y
   14:00 hora de Nueva York, dias habiles).

Salir de una posicion NUNCA se bloquea (regla de trader-risk).
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import pandas as pd
import requests

NY = "America/New_York"
CALENDAR_URLS = (
    "https://nfs.faireconomy.media/ff_calendar_thisweek.json",
    "https://cdn-nfs.faireconomy.media/ff_calendar_thisweek.json",
)
# Palabras clave que, aunque el calendario las marque "Medium", mueven al oro.
GOLD_MOVERS = ("CPI", "PCE", "Non-Farm", "NFP", "Payroll", "FOMC", "Fed Chair", "Federal Funds", "Interest Rate",
               "GDP", "Unemployment", "PPI", "Retail Sales", "ISM", "JOLTS", "Powell", "Beige Book", "Jackson Hole")
FALLBACK_TIMES_NY = ((8, 30), (10, 0), (14, 0))


@dataclass
class NewsConfig:
    enabled: bool = True
    minutes_before: int = 30
    minutes_after: int = 45
    currencies: tuple = ("USD",)
    impacts: tuple = ("High",)
    block_holidays: bool = True

    @classmethod
    def from_env(cls) -> "NewsConfig":
        c = cls()
        c.enabled = (os.environ.get("NEWS_FILTER", "true") or "true").lower() in ("1", "true", "yes", "si")
        c.minutes_before = int(os.environ.get("NEWS_MINUTES_BEFORE", "") or c.minutes_before)
        c.minutes_after = int(os.environ.get("NEWS_MINUTES_AFTER", "") or c.minutes_after)
        return c


@dataclass
class Event:
    time: pd.Timestamp       # UTC
    title: str
    country: str
    impact: str
    forecast: str = ""
    previous: str = ""

    def label(self) -> str:
        ny = self.time.tz_convert(NY)
        return f"{self.title} ({self.country}, {self.impact}) {ny:%a %d/%m %H:%M} NY"


def parse_calendar(items: list[dict]) -> list[Event]:
    out = []
    for it in items or []:
        try:
            t = pd.Timestamp(it["date"])
            t = t.tz_localize(NY) if t.tzinfo is None else t
            out.append(Event(t.tz_convert("UTC"), str(it.get("title", "")), str(it.get("country", "")),
                             str(it.get("impact", "")), str(it.get("forecast", "") or ""),
                             str(it.get("previous", "") or "")))
        except (KeyError, ValueError, TypeError):
            continue
    return sorted(out, key=lambda e: e.time)


def fetch_calendar(timeout: int = 10) -> tuple[list[Event], str]:
    """Devuelve (eventos, fuente). Lista vacia + "fallo" si no hubo forma de leerlo."""
    for url in CALENDAR_URLS:
        try:
            r = requests.get(url, timeout=timeout, headers={"User-Agent": "Mozilla/5.0 (robot-supertrend)"})
            if r.ok:
                return parse_calendar(r.json()), url
        except (requests.RequestException, ValueError):
            continue
    return [], "fallo"


def relevant(e: Event, cfg: NewsConfig) -> bool:
    if e.country not in cfg.currencies:
        return False
    if e.impact in cfg.impacts:
        return True
    return e.impact == "Medium" and any(k.lower() in e.title.lower() for k in GOLD_MOVERS)


def check_news(now: datetime, events: list[Event], source: str, cfg: NewsConfig) -> dict:
    """{'block': bool, 'reason': str, 'next': [eventos proximos]} para NUEVAS entradas."""
    now = pd.Timestamp(now).tz_convert("UTC") if pd.Timestamp(now).tzinfo else pd.Timestamp(now, tz="UTC")
    upcoming = [e for e in events if relevant(e, cfg) and e.time >= now - timedelta(minutes=cfg.minutes_after)][:5]
    if not cfg.enabled:
        return {"block": False, "reason": "filtro de noticias apagado", "next": upcoming, "source": source}
    if source == "fallo":
        ny = now.tz_convert(NY)
        if ny.weekday() < 5:
            for hh, mm in FALLBACK_TIMES_NY:
                t = ny.normalize() + pd.Timedelta(hours=hh, minutes=mm)
                if t - pd.Timedelta(minutes=cfg.minutes_before) <= ny <= t + pd.Timedelta(minutes=cfg.minutes_after):
                    return {"block": True, "next": [], "source": source,
                            "reason": f"calendario no disponible: bloqueo preventivo alrededor de las {hh:02d}:{mm:02d} NY"}
        return {"block": False, "reason": "calendario no disponible (fuera de ventanas habituales)", "next": [],
                "source": source}
    if cfg.block_holidays:
        for e in events:
            if e.country in cfg.currencies and e.impact == "Holiday" and e.time.tz_convert(NY).date() == now.tz_convert(NY).date():
                return {"block": True, "reason": f"feriado en EE. UU. ({e.title}): baja liquidez", "next": upcoming,
                        "source": source}
    for e in events:
        if not relevant(e, cfg):
            continue
        if e.time - timedelta(minutes=cfg.minutes_before) <= now <= e.time + timedelta(minutes=cfg.minutes_after):
            when = "en" if now < e.time else "hace"
            mins = abs(int((e.time - now).total_seconds() // 60))
            return {"block": True, "reason": f"{e.label()} — {when} {mins} min", "next": upcoming, "source": source}
    return {"block": False, "reason": "sin noticias de alto impacto cerca", "next": upcoming, "source": source}
