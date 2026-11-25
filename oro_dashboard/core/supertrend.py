"""Supertrend identico al indicador integrado de TradingView (`ta.supertrend`).

Parametros por defecto de TradingView: ATR length 10, factor 3, fuente hl2, ATR por
RMA (media de Wilder). Reglas pedidas por el usuario:
- Supertrend pasa a VERDE (tendencia alcista)  -> COMPRA.
- Supertrend pasa a ROJO   (tendencia bajista) -> VENTA.
- Se cierra la posicion abierta cuando cambia de color (y se abre la contraria).

Solo cuentan velas CERRADAS: la señal de una vela en formacion puede desaparecer
antes del cierre (igual que en TradingView con alertas "Once per bar close").

Sin dependencias de Streamlit: lo usan tanto el dashboard como el robot.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

DEFAULT_PERIOD = 10
DEFAULT_FACTOR = 3.0


def rma_atr(high: np.ndarray, low: np.ndarray, close: np.ndarray, period: int) -> np.ndarray:
    """ATR de TradingView: true range suavizado con RMA, sembrado con la SMA inicial."""
    prev_close = np.r_[np.nan, close[:-1]]
    tr = np.nanmax(np.column_stack([high - low, np.abs(high - prev_close), np.abs(low - prev_close)]), axis=1)
    atr = np.full(len(tr), np.nan)
    if len(tr) < period:
        return atr
    atr[period - 1] = tr[:period].mean()
    for i in range(period, len(tr)):
        atr[i] = (atr[i - 1] * (period - 1) + tr[i]) / period
    return atr


def supertrend(df: pd.DataFrame, period: int = DEFAULT_PERIOD, factor: float = DEFAULT_FACTOR) -> pd.DataFrame:
    """Devuelve columnas: supertrend (nivel de la linea), trend (+1 verde / -1 rojo),
    buy / sell (True en la vela que cambia de color)."""
    high = df["high"].to_numpy(dtype=float)
    low = df["low"].to_numpy(dtype=float)
    close = df["close"].to_numpy(dtype=float)
    n = len(close)
    atr = rma_atr(high, low, close, period)
    src = (high + low) / 2
    basic_up = src + factor * atr
    basic_lo = src - factor * atr

    upper = np.full(n, np.nan)
    lower = np.full(n, np.nan)
    trend = np.zeros(n, dtype=int)
    line = np.full(n, np.nan)
    for i in range(n):
        if np.isnan(atr[i]):
            continue
        if i == 0 or np.isnan(upper[i - 1]):
            upper[i], lower[i] = basic_up[i], basic_lo[i]
            trend[i] = -1  # TradingView arranca en rojo cuando no hay ATR previo
        else:
            lower[i] = basic_lo[i] if (basic_lo[i] > lower[i - 1] or close[i - 1] < lower[i - 1]) else lower[i - 1]
            upper[i] = basic_up[i] if (basic_up[i] < upper[i - 1] or close[i - 1] > upper[i - 1]) else upper[i - 1]
            if trend[i - 1] == -1:   # la linea previa era la banda superior (rojo)
                trend[i] = 1 if close[i] > upper[i] else -1
            else:                    # la linea previa era la banda inferior (verde)
                trend[i] = -1 if close[i] < lower[i] else 1
        line[i] = lower[i] if trend[i] == 1 else upper[i]

    out = pd.DataFrame({"supertrend": line, "trend": trend}, index=df.index)
    prev = out["trend"].shift(1).fillna(0).astype(int)
    out["buy"] = (out["trend"] == 1) & (prev == -1)
    out["sell"] = (out["trend"] == -1) & (prev == 1)
    return out


def backtest_flip(df: pd.DataFrame, st: pd.DataFrame, cost: float = 0.5) -> dict:
    """Siempre en mercado: compra al ponerse verde, vende al ponerse rojo, cierra y da
    vuelta en cada cambio de color. Ejecucion a la APERTURA de la vela siguiente a la
    señal (como un robot que espera el cierre de la vela). `cost` = spread +
    deslizamiento en USD por operacion (1 onza = tamaño 1 del CFD GOLD de Capital.com)."""
    opens = df["open"].to_numpy(dtype=float)
    signal_idx = np.flatnonzero((st["buy"] | st["sell"]).to_numpy())
    signal_idx = signal_idx[signal_idx + 1 < len(df)]
    trades = []
    for a, b in zip(signal_idx[:-1], signal_idx[1:]):
        side = 1 if st["buy"].iloc[a] else -1
        entry, exit_ = opens[a + 1], opens[b + 1]
        pnl = side * (exit_ - entry) - cost
        trades.append({
            "entrada": df.index[a + 1], "salida": df.index[b + 1], "lado": "COMPRA" if side == 1 else "VENTA",
            "precio_entrada": entry, "precio_salida": exit_, "pnl": pnl, "velas": int(b - a),
        })
    if not trades:
        return {"n": 0, "trades": pd.DataFrame()}
    t = pd.DataFrame(trades)
    wins, losses = t.loc[t.pnl > 0, "pnl"], t.loc[t.pnl <= 0, "pnl"]
    equity = t["pnl"].cumsum()
    max_dd = float((equity.cummax() - equity).max())
    return {
        "n": int(len(t)), "win_rate": float((t.pnl > 0).mean()),
        "profit_factor": float(wins.sum() / -losses.sum()) if losses.sum() < 0 else float("inf"),
        "net": float(t.pnl.sum()), "avg": float(t.pnl.mean()), "avg_win": float(wins.mean()) if len(wins) else 0.0,
        "avg_loss": float(losses.mean()) if len(losses) else 0.0, "max_dd": max_dd,
        "long_net": float(t.loc[t.lado == "COMPRA", "pnl"].sum()),
        "short_net": float(t.loc[t.lado == "VENTA", "pnl"].sum()),
        "equity": equity.to_numpy(), "trades": t, "cost": cost,
    }


def current_state(df: pd.DataFrame, st: pd.DataFrame, closed_only: bool = True) -> dict:
    """Estado vigente para mostrar / ejecutar. Con `closed_only` ignora la ultima vela
    (en formacion) para no actuar sobre una señal que aun puede desaparecer."""
    d, s = (df.iloc[:-1], st.iloc[:-1]) if closed_only and len(df) > 1 else (df, st)
    flips = np.flatnonzero((s["buy"] | s["sell"]).to_numpy())
    last = int(flips[-1]) if len(flips) else None
    trend = int(s["trend"].iloc[-1])
    return {
        "trend": trend, "label": "COMPRA" if trend == 1 else "VENTA",
        "since": d.index[last] if last is not None else None,
        "signal_close": float(d["close"].iloc[last]) if last is not None else None,
        "line": float(s["supertrend"].iloc[-1]),
        "last_closed_bar": d.index[-1], "bars_since": int(len(d) - 1 - last) if last is not None else None,
        "new_signal_on_last_bar": bool(last == len(d) - 1),
    }
