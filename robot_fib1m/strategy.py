"""Estrategia "Fibonacci 1m con confirmacion" (estilo manual del usuario) sobre bid/ask reales.

Elegida en research/manual_style (gano en entrenamiento y prueba, 87 ops en 25 dias):
1. Impulso: ZigZag causal en velas 1m (precio medio), giro de 2,5 ATR(14), tramo >= 5 ATR,
   a favor de la tendencia Supertrend 10/3 de 15m Y de 1h (velas ya cerradas).
2. Entrada con confirmacion: el precio toca el retroceso 0,618 y una vela 1m CIERRA de
   vuelta por encima de 0,5 (compra; espejo para venta). Se ejecuta a la apertura de la
   vela siguiente: compra al ASK, venta al BID (spread real incluido).
3. Stop fijo de $2,50 desde el precio de entrada; objetivo en la extension 1,272 del
   impulso. SIN stop a cero (en el backtest el stop a cero anulaba la ganancia).
4. La compra sale cuando el BID toca stop u objetivo; la venta, cuando lo toca el ASK.
   Si una vela toca los dos, cuenta el stop (conservador). Maximo 240 velas abierta.
5. Filtro de spread opcional: no entra si el spread al momento de la señal supera
   `max_spread` (de noche el spread del oro llega a $1-2, casi todo el stop).

Solo numpy/pandas: lo usan la prueba en simulacion (forward.py) y, mas adelante, el robot.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "oro_dashboard"))
from core.supertrend import rma_atr, supertrend  # noqa: E402

ZZ_ATR = 2.5
IMPULSE_ATR = 5.0
SETUP_BARS = 60
MAX_HOLD = 240
STOP_USD = 2.50
TARGET_EXT = 0.272          # extension 1,272 = B + 0,272 * (B - A)
NY = "America/New_York"


def tradable_mask(index: pd.DatetimeIndex) -> np.ndarray:
    """Oro spot abierto: dom 18:00 -> vie 17:00 NY, sin la pausa diaria 17:00-18:00."""
    ny = index.tz_convert(NY)
    wd, hr = ny.weekday, ny.hour
    closed = (wd == 5) | ((wd == 4) & (hr >= 17)) | ((wd == 6) & (hr < 18)) | (hr == 17)
    return ~np.asarray(closed)


def htf_trend(mid: pd.DataFrame, minutes: int, period=10, factor=3.0) -> np.ndarray:
    """Tendencia Supertrend de una temporalidad mayor, alineada sin mirar el futuro."""
    r = mid.resample(f"{minutes}min", label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
    st = supertrend(r, period, factor)["trend"]
    st.index = st.index + pd.Timedelta(minutes=minutes)  # disponible al cierre de la vela mayor
    return st.reindex(mid.index, method="ffill").fillna(0).to_numpy()


def impulses(h, l, atr):
    out, d, ext, origin = [], 1, h[0], l[0]
    for i in range(1, len(h)):
        if not np.isfinite(atr[i]):
            continue
        if d == 1:
            if h[i] > ext:
                ext = h[i]
            elif ext - l[i] >= ZZ_ATR * atr[i]:
                if ext - origin >= IMPULSE_ATR * atr[i]:
                    out.append((i, origin, ext, 1))
                d, origin, ext = -1, ext, l[i]
        else:
            if l[i] < ext:
                ext = l[i]
            elif h[i] - ext >= ZZ_ATR * atr[i]:
                if origin - ext >= IMPULSE_ATR * atr[i]:
                    out.append((i, origin, ext, -1))
                d, origin, ext = 1, ext, h[i]
    return out


def split_bid_ask(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """df con columnas open_bid, open_ask, high_bid, ... -> (bid, ask, medio)."""
    cols = ("open", "high", "low", "close")
    bid = pd.DataFrame({c: df[f"{c}_bid"] for c in cols}, index=df.index)
    ask = pd.DataFrame({c: df[f"{c}_ask"] for c in cols}, index=df.index)
    return bid, ask, (bid + ask) / 2


def simulate(df: pd.DataFrame, max_spread: float | None = None, stop_usd: float = STOP_USD,
             target_ext: float = TARGET_EXT) -> pd.DataFrame:
    """Operaciones que habria hecho la estrategia. Devuelve una fila por operacion."""
    bid, ask, mid = split_bid_ask(df)
    ob, hb, lb = bid["open"].to_numpy(), bid["high"].to_numpy(), bid["low"].to_numpy()
    oa, ha, la = ask["open"].to_numpy(), ask["high"].to_numpy(), ask["low"].to_numpy()
    hm, lm, cm = mid["high"].to_numpy(), mid["low"].to_numpy(), mid["close"].to_numpy()
    spread = (df["close_ask"] - df["close_bid"]).to_numpy()
    ok = tradable_mask(df.index)
    atr = rma_atr(hm, lm, cm, 14)
    t15, t60 = htf_trend(mid, 15), htf_trend(mid, 60)
    imps = {i: (a, b, s) for i, a, b, s in impulses(hm, lm, atr)}
    trades, i, n = [], 0, len(df)
    while i < n - 2:
        if i not in imps:
            i += 1
            continue
        a, b, s = imps[i]
        if not (t15[i] == s and t60[i] == s):
            i += 1
            continue
        leg = abs(b - a)
        z50, z618 = b - s * 0.5 * leg, b - s * 0.618 * leg
        j, entry_i, touched, skipped = i + 1, None, False, None
        while j < min(n - 1, i + 1 + SETUP_BARS):
            if (s == 1 and (hm[j] > b or lm[j] < a)) or (s == -1 and (lm[j] < b or hm[j] > a)):
                break  # siguio sin retroceder, o rompio el origen: setup invalido
            touched |= (s == 1 and lm[j] <= z618) or (s == -1 and hm[j] >= z618)
            if touched and ((s == 1 and cm[j] > z50) or (s == -1 and cm[j] < z50)) and ok[j + 1]:
                if max_spread is not None and spread[j] > max_spread:
                    skipped = j
                else:
                    entry_i = j + 1
                break
            j += 1
        if entry_i is None:
            if skipped is not None:
                trades.append({"time": df.index[skipped + 1], "side": s, "skipped": True, "spread": spread[skipped]})
            i = j + 1
            continue
        px = oa[entry_i] if s == 1 else ob[entry_i]
        stop = px - s * stop_usd
        target = b + s * target_ext * leg
        if s * (target - px) <= 0:
            i = entry_i + 1
            continue
        k, exit_px, reason = entry_i, None, None
        while k < n:
            if not ok[k] or k - entry_i > MAX_HOLD:
                exit_px, reason = (ob[k] if s == 1 else oa[k]), "tiempo/cierre"
                break
            lo, hi, op = (lb[k], hb[k], ob[k]) if s == 1 else (la[k], ha[k], oa[k])
            if (s == 1 and lo <= stop) or (s == -1 and hi >= stop):
                exit_px = (min(stop, op) if s == 1 else max(stop, op)) if k > entry_i else stop
                reason = "stop"
                break
            if k > entry_i and ((s == 1 and hi >= target) or (s == -1 and lo <= target)):
                exit_px, reason = target, "objetivo"
                break
            k += 1
        if exit_px is None:
            k = n - 1
            exit_px, reason = (lb[k] if s == 1 else la[k]), "abierta"
        pnl = s * (exit_px - px)
        trades.append({"time": df.index[entry_i], "exit_time": df.index[k], "side": s, "entry": px,
                       "stop": stop, "target": target, "exit": exit_px, "reason": reason, "pnl": pnl,
                       "R": pnl / stop_usd, "spread": spread[entry_i - 1], "skipped": False})
        i = k + 1
    return pd.DataFrame(trades)


def equity(trades: pd.DataFrame, risk_pct: float, leverage: float, start: float = 10.0) -> tuple[float, float]:
    """Capital final y caida maxima con riesgo fijo por operacion (tamaño minimo 0,01 oz)."""
    eq, peak, mdd = start, start, 0.0
    for t in trades[~trades["skipped"]].itertuples():
        if t.reason == "abierta":
            continue
        size = min(eq * risk_pct / STOP_USD, eq * leverage / t.entry)
        size = np.floor(size / 0.01 + 1e-9) * 0.01
        if size < 0.01:
            break
        eq = max(eq + size * t.pnl, 0.0)
        peak, mdd = max(peak, eq), max(mdd, 1 - eq / peak if peak else 0)
    return eq, mdd
