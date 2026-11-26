"""Backtest: ruptura del rango de la primera vela de 15 minutos + retesteo, objetivo PDH/PDL.

Estrategia del video compartido por el usuario:
- Marcar maximo y minimo de la primera vela de 15 minutos de la sesion.
- Compra: una vela CIERRA por encima del maximo de 15m (ruptura), el precio vuelve a tocar
  ese nivel (retesteo) y una vela vuelve a cerrar por encima -> entrada a la apertura
  siguiente. Stop justo debajo del maximo de 15m. Objetivo: maximo del dia anterior (PDH).
- Venta: espejo con el minimo de 15m y el minimo del dia anterior (PDL).

Reglas objetivas: velas de 5 minutos de GC=F (60 dias, el maximo de Yahoo), una operacion por
sesion y dia, ventana de 4 h para entrar y 8 h maximo abierta; si una vela toca stop y
objetivo cuenta el stop; spread real medido en Capital.com ($0,50) y sensibilidad a $0,30.
Sesiones probadas (hora de Nueva York): apertura de NY 09:30, Londres 03:00, diaria 18:00.

Uso: python research/orb_pdh/backtest_orb.py
"""
from __future__ import annotations

import itertools
from pathlib import Path

import numpy as np
import pandas as pd

NY = "America/New_York"
SESSIONS = {"Nueva York 09:30": (9, 30), "Londres 03:00": (3, 0), "Diaria 18:00": (18, 0)}
ENTRY_WINDOW_H, MAX_HOLD_H = 4, 8


def trading_day(idx: pd.DatetimeIndex) -> np.ndarray:
    """Dia de trading del oro: empieza a las 18:00 NY del dia anterior."""
    ny = idx.tz_convert(NY)
    return np.asarray((ny + pd.Timedelta(hours=6)).date)


def run(df: pd.DataFrame, session: str, stop_mode: str, min_rr: float, cost: float) -> pd.DataFrame:
    ny = df.index.tz_convert(NY)
    tday = trading_day(df.index)
    daily = df.groupby(tday).agg(high=("high", "max"), low=("low", "min"))
    prev = daily.shift(1)
    o, h, l, c = (df[k].to_numpy() for k in ("open", "high", "low", "close"))
    hh, mm = SESSIONS[session]
    starts = np.flatnonzero((ny.hour == hh) & (ny.minute == mm))
    trades = []
    for s0 in starts:
        rng_end = s0 + 3  # 3 velas de 5m = la primera vela de 15m
        if rng_end + 2 >= len(df) or (df.index[rng_end] - df.index[s0]) > pd.Timedelta(minutes=20):
            continue
        h15, l15 = h[s0:rng_end].max(), l[s0:rng_end].min()
        day = tday[rng_end]
        if day not in prev.index or pd.isna(prev.loc[day, "high"]):
            continue
        pdh, pdl = prev.loc[day, "high"], prev.loc[day, "low"]
        limit = df.index[rng_end] + pd.Timedelta(hours=ENTRY_WINDOW_H)
        broke, retested, side, entry_i = 0, False, 0, None
        j = rng_end
        while j < len(df) - 1 and df.index[j] < limit:
            if broke == 0:
                if c[j] > h15:
                    broke = 1
                elif c[j] < l15:
                    broke = -1
            elif broke == 1:
                if c[j] < l15:
                    break  # el rompimiento fallo del todo
                retested |= l[j] <= h15
                if retested and c[j] > h15:
                    side, entry_i = 1, j + 1
                    break
            else:
                if c[j] > h15:
                    break
                retested |= h[j] >= l15
                if retested and c[j] < l15:
                    side, entry_i = -1, j + 1
                    break
            j += 1
        if entry_i is None:
            continue
        px = o[entry_i] + side * cost / 2  # compra al ask, vende al bid
        level = h15 if side == 1 else l15
        buf = 0.1 * (h15 - l15)
        stop = (level - side * buf) if stop_mode == "debajo del nivel" else (l15 if side == 1 else h15)
        target = pdh if side == 1 else pdl
        risk, reward = side * (px - stop), side * (target - px)
        if risk <= 0.05 or reward <= 0 or reward < min_rr * risk:
            continue
        k, exit_px, reason = entry_i, None, None
        end = df.index[entry_i] + pd.Timedelta(hours=MAX_HOLD_H)
        while k < len(df):
            if df.index[k] > end:
                exit_px, reason = o[k] - side * cost / 2, "tiempo"
                break
            if (side == 1 and l[k] - cost / 2 <= stop) or (side == -1 and h[k] + cost / 2 >= stop):
                exit_px, reason = (min(stop, o[k] - cost / 2) if side == 1 else max(stop, o[k] + cost / 2)), "stop"
                break
            if k > entry_i and ((side == 1 and h[k] - cost / 2 >= target) or (side == -1 and l[k] + cost / 2 <= target)):
                exit_px, reason = target, "objetivo"
                break
            k += 1
        if exit_px is None:
            continue
        pnl = side * (exit_px - px)
        trades.append({"time": df.index[entry_i], "side": side, "pnl": pnl, "R": pnl / risk, "risk": risk,
                       "reward": reward, "reason": reason})
    return pd.DataFrame(trades)


def main():
    here = Path(__file__).resolve().parent
    df = pd.read_pickle(here / ".cache" / "GC_F_5m.pkl")
    df.index = pd.DatetimeIndex(df.index).tz_convert("UTC")
    half = df.index[len(df) // 2]
    rng = np.random.default_rng(19)
    days = len(np.unique(trading_day(df.index)))
    print(f"GC=F 5m: {len(df):,} velas, {days} dias de trading ({df.index[0]:%d/%m} -> {df.index[-1]:%d/%m/%Y}); mitad {half:%d/%m}")
    print("sesion | stop | R:R min | ops | acierto | R medio (IC 95 %) | $/oz | 1.a/2.a mitad R | con spread $0,30 R | motivos")
    for ses, sm, rr in itertools.product(SESSIONS, ("debajo del nivel", "otro extremo de 15m"), (1.0, 2.0)):
        t = run(df, ses, sm, rr, cost=0.50)
        if t.empty:
            print(f"{ses} | {sm} | {rr} | 0")
            continue
        b = rng.choice(t.R.to_numpy(), size=(3000, len(t))).mean(1)
        a1, a2 = t[t.time < half].R.mean(), t[t.time >= half].R.mean()
        t3 = run(df, ses, sm, rr, cost=0.30)
        print(f"{ses} | {sm} | {rr:g} | {len(t)} | {(t.pnl > 0).mean() * 100:.0f}% | {t.R.mean():+.2f} ({np.percentile(b, 2.5):+.2f} a "
              f"{np.percentile(b, 97.5):+.2f}) | {t.pnl.mean():+.2f} | {a1:+.2f} / {a2:+.2f} | {t3.R.mean():+.2f} | "
              f"{t.reason.value_counts().to_dict()}")


if __name__ == "__main__":
    main()
