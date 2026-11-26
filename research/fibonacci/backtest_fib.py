"""Backtest de Fibonacci (retroceso + extension por tendencia, como en TradingView) para el oro.

Reglas objetivas (sin mirar el futuro):
1. Impulsos: un ZigZag causal confirma un maximo (o minimo) cuando el precio se aleja
   ZZ_ATR x ATR(14) de el. Un tramo A->B cuenta como impulso si mide >= IMPULSE_ATR x ATR.
2. Entrada: orden limitada en el retroceso r de A->B (0,5 o 0,618: la "zona dorada"),
   a favor del impulso (impulso alcista -> compra en el retroceso; bajista -> venta).
   Se cancela si el precio supera B antes de llenarse o pasan CANCEL_BARS velas.
3. Stop: nivel 0,786, origen del impulso (1,0), fijo de $2, o SIN stop (solo el cierre
   por margen del broker, asumido al 50 % del margen usado).
4. Objetivo: volver a B (retroceso 0 %) o extension 1,0 desde el punto de entrada C
   (C + (B - A), la "Trend-Based Fib Extension" de TradingView).
5. Ejecucion conservadora: si una vela toca stop y objetivo, cuenta el stop; en la vela
   de llenado solo puede tocar el stop. Costo $0,30/oz por operacion.

Cuenta: $10 iniciales; cada operacion usa MARGIN_PCT del capital como margen con
apalancamiento 1:20 (tamaño minimo 0,01 oz, paso 0,01). Si el tamaño minimo no entra, la
cuenta queda sin poder operar (quiebra practica).

Uso: python research/fibonacci/backtest_fib.py
"""
from __future__ import annotations

import itertools
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "oro_dashboard"))
from core.supertrend import rma_atr  # noqa: E402

NY = "America/New_York"
COST = 0.30
LEVERAGE = 20.0
MARGIN_CALL = 0.5
START = 10.0
MARGIN_PCT = 0.60
ZZ_ATR, IMPULSE_ATR, CANCEL_BARS, MAX_HOLD = 2.5, 4.0, 48, 240


def tradable(df: pd.DataFrame) -> pd.DataFrame:
    ny = df.index.tz_convert(NY)
    wd, hr = ny.weekday, ny.hour
    closed = (wd == 5) | ((wd == 4) & (hr >= 17)) | ((wd == 6) & (hr < 18))
    return df[~np.asarray(closed)]


def impulses(h, l, atr):
    """ZigZag causal. Devuelve (bar_confirmacion, A, B, lado) por impulso confirmado."""
    out, d = [], 1
    ext, ext_i, origin = h[0], 0, l[0]
    for i in range(1, len(h)):
        if not np.isfinite(atr[i]):
            continue
        if d == 1:
            if h[i] > ext:
                ext, ext_i = h[i], i
            elif ext - l[i] >= ZZ_ATR * atr[i]:
                if ext - origin >= IMPULSE_ATR * atr[i]:
                    out.append((i, origin, ext, 1))
                d, origin, ext, ext_i = -1, ext, l[i], i
        else:
            if l[i] < ext:
                ext, ext_i = l[i], i
            elif h[i] - ext >= ZZ_ATR * atr[i]:
                if origin - ext >= IMPULSE_ATR * atr[i]:
                    out.append((i, origin, ext, -1))
                d, origin, ext, ext_i = 1, ext, h[i], i
    return out


def backtest(df: pd.DataFrame, entry_r: float, stop_mode: str, target_mode: str, margin_pct=MARGIN_PCT):
    o, h, l, c = (df[k].to_numpy() for k in ("open", "high", "low", "close"))
    atr = rma_atr(h, l, c, 14)
    imps = {i: (a, b, s) for i, a, b, s in impulses(h, l, atr)}
    eq, peak, max_dd = START, START, 0.0
    per_oz, entries, n, i = [], [], len(df), 0
    broke = False
    while i < n - 1:
        if i not in imps:
            i += 1
            continue
        a, b, s = imps[i]
        leg = abs(b - a)
        entry = b - s * entry_r * leg
        if stop_mode == "0.786":
            stop = b - s * 0.786 * leg
        elif stop_mode == "1.0":
            stop = a - s * 0.01
        elif stop_mode == "$2":
            stop = entry - s * 2.0
        else:
            stop = None
        target = b if target_mode == "B" else entry + s * leg
        # esperar el llenado
        j, filled = i + 1, None
        while j < min(n, i + 1 + CANCEL_BARS):
            if (s == 1 and h[j] > b) or (s == -1 and l[j] < b):
                break  # el impulso siguio sin retroceder: se cancela
            if (s == 1 and l[j] <= entry) or (s == -1 and h[j] >= entry):
                filled = (j, min(entry, o[j]) if s == 1 else max(entry, o[j]))
                break
            j += 1
        if filled is None:
            i = j
            continue
        j, px_in = filled
        if stop_mode == "$2":
            stop = px_in - s * 2.0  # $2 desde el precio REAL de llenado
        if (stop is not None and s * (px_in - stop) <= 0) or s * (target - px_in) <= 0:
            i = j + 1  # el precio ya salto mas alla del stop/objetivo: no hay operacion valida
            continue
        size = np.floor(eq * margin_pct * LEVERAGE / px_in / 0.01 + 1e-9) * 0.01
        if size < 0.01:
            broke = True
            break
        margin = size * px_in / LEVERAGE
        liq = px_in - s * (eq - MARGIN_CALL * margin) / size  # precio de cierre por margen
        eff_stop = liq if stop is None else (max(stop, liq) if s == 1 else min(stop, liq))
        exit_px, k = None, j
        while k < n:
            if k > j + MAX_HOLD:
                exit_px = o[k]
                break
            if (s == 1 and l[k] <= eff_stop) or (s == -1 and h[k] >= eff_stop):
                exit_px = min(eff_stop, o[k]) if (s == 1 and k > j) else (max(eff_stop, o[k]) if k > j else eff_stop)
                break
            if k > j and ((s == 1 and h[k] >= target) or (s == -1 and l[k] <= target)):
                exit_px = target
                break
            k += 1
        if exit_px is None:
            exit_px, k = c[-1], n - 1
        pnl_oz = s * (exit_px - px_in) - COST
        per_oz.append(pnl_oz)
        entries.append(j)
        eq = max(eq + pnl_oz * size, 0.0)
        peak = max(peak, eq)
        max_dd = max(max_dd, (peak - eq) / peak)
        i = k + 1
    r = np.array(per_oz)
    return {"n": len(r), "win": float((r > 0).mean()) if len(r) else np.nan,
            "exp": float(r.mean()) if len(r) else np.nan, "final": eq, "max_dd": max_dd,
            "broke": broke or eq < 0.5, "per_oz": r, "entries": np.array(entries)}


def main():
    here = Path(__file__).resolve().parent
    data = {
        "1h GC=F (2 años)": pd.read_pickle(ROOT / "research/scaling_1h/.cache/GC_F_1h.pkl"),
        "1h PAXG (2 años)": pd.read_pickle(ROOT / "research/scaling_1h/.cache/PAXG-USD_1h.pkl"),
        "15m GC=F (60 dias)": tradable(pd.read_pickle(here / ".cache/GC_F_15m.pkl")),
        "5m GC=F (60 dias)": tradable(pd.read_pickle(here / ".cache/GC_F_5m.pkl")),
    }
    rng = np.random.default_rng(19)
    lines = ["# Fibonacci (retroceso + extension) — backtest con cuenta de $10", "",
             f"Margen por operacion {MARGIN_PCT:.0%} del capital, apalancamiento 1:{LEVERAGE:.0f}, costo ${COST}/oz, "
             f"cierre por margen al {MARGIN_CALL:.0%}. ZigZag {ZZ_ATR} ATR, impulso >= {IMPULSE_ATR} ATR.", ""]
    for name, df in data.items():
        lines += [f"## {name}", "",
                  "| Entrada | Stop | Objetivo | Ops | Acierto | $/oz por op (IC 95 %) | 1.ª mitad / 2.ª mitad $/oz | $10 terminan en | Caida max | Quiebra |",
                  "|---|---|---|---|---|---|---|---|---|---|"]
        half = len(df) // 2
        for er, sm, tm in itertools.product((0.5, 0.618), ("0.786", "1.0", "$2", "sin stop"), ("B", "ext 1.0")):
            r = backtest(df, er, sm, tm)
            if r["n"] == 0:
                continue
            boot = rng.choice(r["per_oz"], size=(3000, r["n"])).mean(1)
            first = r["entries"] < half
            h1 = r["per_oz"][first].mean() if first.any() else np.nan
            h2 = r["per_oz"][~first].mean() if (~first).any() else np.nan
            lines.append(
                f"| {er} | {sm} | {tm} | {r['n']} | {r['win'] * 100:.0f} % | {r['exp']:+.2f} ({np.percentile(boot, 2.5):+.2f} a "
                f"{np.percentile(boot, 97.5):+.2f}) | {h1:+.2f} / {h2:+.2f} | ${r['final']:,.2f} | {r['max_dd'] * 100:.0f} % | "
                f"{'SI' if r['broke'] else 'no'} |")
        lines.append("")
    text = "\n".join(lines)
    (here / "resultados.md").write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
