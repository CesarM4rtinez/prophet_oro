"""Simulacion de trades secuenciales (no solapados) sobre el mismo criterio de
Entry/Stoploss/Target1/Target2 que `core.probability`, para producir una curva de
equity y un log de trades — al estilo de los paneles de backtest (equity, P/L por
trade, precio con marcadores de compra/venta) de frameworks de trading algoritmico.

Diferencia clave con `backtest_targets` (core/probability.py): ese backtest cuenta,
para CADA ventana deslizante de 30 velas, si se toco primero el target o el stop
(ventanas solapadas, sin simular una cuenta real). Este modulo en cambio abre UN
trade a la vez y avanza al siguiente solo cuando el anterior se resuelve (o expira),
para poder acumular una curva de capital como lo haria una cuenta real operando esta
regla de forma mecanica."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .probability import direction_levels


def simulate_trades(
    df: pd.DataFrame,
    direction: str = "compra",
    sl_pct: float = 0.01,
    t1_pct: float = 0.01,
    t2_pct: float = 0.02,
    max_hold: int = 30,
    initial_capital: float = 10_000.0,
) -> dict:
    """Recorre `df` abriendo un trade a la entrada de cada vela libre (entry=close),
    con SL/Target1/Target2 segun `direction_levels`. El trade se cierra en el primer
    nivel tocado (mirando solo cierres, igual criterio que `backtest_targets`) o, si
    no se toca ninguno en `max_hold` velas, se cierra al cierre de esa ultima vela
    ("Timeout"). El capital se compone 100% por trade (sin apalancamiento ni
    position sizing fraccionado) — una simplificacion pensada para ilustrar la forma
    de la curva, no una simulacion de gestion de riesgo real."""
    close = df["close"].to_numpy(dtype=float)
    n = len(close)

    trades: list[dict] = []
    i = 0
    while i < n - 1:
        entry_idx = i
        entry_price = close[i]
        sl, t1, t2 = direction_levels(entry_price, sl_pct, t1_pct, t2_pct, direction)
        end = min(i + max_hold, n - 1)

        exit_idx, exit_price, result = None, None, None
        for j in range(i + 1, end + 1):
            price = close[j]
            if direction == "compra":
                if price <= sl:
                    exit_idx, exit_price, result = j, sl, "Stoploss"
                    break
                if price >= t2:
                    exit_idx, exit_price, result = j, t2, "Target2"
                    break
                if price >= t1:
                    exit_idx, exit_price, result = j, t1, "Target1"
                    break
            else:
                if price >= sl:
                    exit_idx, exit_price, result = j, sl, "Stoploss"
                    break
                if price <= t2:
                    exit_idx, exit_price, result = j, t2, "Target2"
                    break
                if price <= t1:
                    exit_idx, exit_price, result = j, t1, "Target1"
                    break

        if exit_idx is None:
            exit_idx, exit_price, result = end, close[end], "Timeout"

        pnl_pct = (exit_price / entry_price - 1) if direction == "compra" else (entry_price / exit_price - 1)
        trades.append(
            {
                "entry_idx": entry_idx, "exit_idx": exit_idx,
                "entry_time": df.index[entry_idx], "exit_time": df.index[exit_idx],
                "entry_price": entry_price, "exit_price": exit_price,
                "result": result, "pnl_pct": pnl_pct,
            }
        )
        i = exit_idx + 1

    equity = [initial_capital]
    for t in trades:
        equity.append(equity[-1] * (1 + t["pnl_pct"]))
    equity = equity[1:]

    wins = sum(1 for t in trades if t["pnl_pct"] > 0)
    total = len(trades) or 1
    buy_hold_return = (close[-1] / close[0] - 1) if direction == "compra" else (close[0] / close[-1] - 1)

    return {
        "trades": trades,
        "equity": equity,
        "final_capital": equity[-1] if equity else initial_capital,
        "initial_capital": initial_capital,
        "total_return_pct": (equity[-1] / initial_capital - 1) * 100 if equity else 0.0,
        "win_rate_pct": wins / total * 100,
        "n_trades": len(trades),
        "buy_hold_return_pct": buy_hold_return * 100,
    }
