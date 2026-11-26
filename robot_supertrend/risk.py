"""Gestion de riesgo y tamaño adaptable al capital (compartido por robot y backtest).

Ideas tomadas de las skills de day-trader-skill, adaptadas a un CFD de oro:
- trader-budget: el tamaño sale del riesgo maximo por operacion; si el stop queda tan
  lejos que ni el tamaño minimo cabe en el riesgo, NO se opera (no se "achica" a la fuerza).
- trader-risk: stop obligatorio y del lado correcto, limite de perdida diaria, tope de
  posiciones, margen y duplicados; salir nunca se bloquea.
- trader-exit: stop en multiplos de ATR.

Escalado (pedido del usuario): el riesgo TOTAL de la cuenta (p. ej. 2 %) se reparte entre
las N posiciones que el capital permite. Con mas capital, N sube (mas operaciones
simultaneas) y cada una arriesga una fraccion menor, manteniendo el riesgo total igual.
El tamaño de cada posicion crece con el capital (riesgo fijo en %), y se achica solo
cuando la cuenta baja.
"""
from __future__ import annotations

import math
import os
from dataclasses import dataclass


def _f(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, "") or default)
    except ValueError:
        return default


@dataclass
class RiskConfig:
    total_risk_pct: float = 1.5          # riesgo total maximo abierto (% del capital)
    # (capital minimo, posiciones simultaneas maximas)
    tiers: tuple = ((0, 1), (2_000, 2), (10_000, 3), (50_000, 4))
    stop_atr: float = 1.0                # stop = linea Supertrend -/+ stop_atr * ATR
    add_every_atr: float = 1.0           # agrega una posicion cada vez que avanza 1 ATR a favor
    daily_loss_pct: float = 3.0          # pausa nuevas entradas el resto del dia
    max_drawdown_pct: float = 25.0       # pausa nuevas entradas hasta revision manual
    min_size: float = 0.01               # se reemplaza por las reglas reales del mercado
    size_step: float = 0.01
    leverage: float = 20.0
    max_margin_pct: float = 50.0         # nunca comprometer mas de este % del capital en margen
    cost_per_unit: float = 0.30          # spread + deslizamiento estimado (USD por onza)

    @classmethod
    def from_env(cls) -> "RiskConfig":
        c = cls()
        c.total_risk_pct = _f("RISK_TOTAL_PCT", c.total_risk_pct)
        c.stop_atr = _f("RISK_STOP_ATR", c.stop_atr)
        c.add_every_atr = _f("RISK_ADD_EVERY_ATR", c.add_every_atr)
        c.daily_loss_pct = _f("RISK_DAILY_LOSS_PCT", c.daily_loss_pct)
        c.max_drawdown_pct = _f("RISK_MAX_DRAWDOWN_PCT", c.max_drawdown_pct)
        c.leverage = _f("RISK_LEVERAGE", c.leverage)
        c.max_margin_pct = _f("RISK_MAX_MARGIN_PCT", c.max_margin_pct)
        max_units = int(_f("RISK_MAX_UNITS", 0))
        if max_units > 0:  # tope manual opcional
            c.tiers = tuple((cap, min(n, max_units)) for cap, n in c.tiers)
        return c


def max_units_for_equity(equity: float, cfg: RiskConfig) -> int:
    n = 1
    for cap, units in cfg.tiers:
        if equity >= cap:
            n = units
    return max(1, n)


def round_down(x: float, step: float) -> float:
    return math.floor(x / step + 1e-9) * step


def position_size(equity: float, entry: float, stop: float, n_max: int, open_size: float,
                  cfg: RiskConfig) -> tuple[float, str]:
    """Tamaño de UNA posicion nueva y la razon que lo decidio.
    riesgo por posicion = capital * riesgo_total% / N  ->  tamaño = riesgo / (distancia stop + costo)"""
    dist = abs(entry - stop)
    if dist <= 0:
        return 0.0, "stop invalido (en el precio de entrada)"
    risk_cash = equity * cfg.total_risk_pct / 100 / n_max
    by_risk = risk_cash / (dist + cfg.cost_per_unit)
    by_margin = (equity * cfg.max_margin_pct / 100 * cfg.leverage) / entry - open_size
    size = round_down(min(by_risk, by_margin), cfg.size_step)
    reason = "riesgo" if by_risk <= by_margin else "margen"
    if size < cfg.min_size:
        return 0.0, (f"el stop esta a ${dist:.2f}: ni el tamaño minimo ({cfg.min_size}) cabe en el riesgo de "
                     f"${risk_cash:.2f} por posicion" if reason == "riesgo" else "sin margen disponible")
    return size, reason


def open_risk(positions: list[dict]) -> float:
    """Riesgo abierto (USD) de las posiciones cuyo stop aun no asegura ganancia."""
    total = 0.0
    for p in positions:
        stop = p.get("stopLevel")
        if stop is None:
            return float("inf")  # sin stop = riesgo ilimitado
        side = 1 if p["direction"] == "BUY" else -1
        loss = side * (p["level"] - float(stop)) * p["size"]
        total += max(loss, 0.0)
    return total
