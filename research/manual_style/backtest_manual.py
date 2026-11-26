"""Backtest del estilo de trading manual del usuario, convertido en reglas (oro, velas de 1 minuto).

Lo que hace el usuario a mano (capturas del 19-20/11/2026, cuenta de $10 a $135):
- Dibuja el Fibonacci del ultimo impulso en 1m y entra en el retroceso, a favor de la
  tendencia de temporalidades mayores ("Confluencia MTF").
- Stop chico (~$2 por onza), objetivo en un nivel (0 o extension).
- Mueve el stop a cero / a ganancia cuando la operacion avanza.
- Tamaño grande (2,9-6,1 oz con ~$100 de capital: apalancamiento ~1:200).

Reglas (sin mirar el futuro, velas 1m de GC=F, ~28 dias, el maximo que da Yahoo):
1. Impulso: ZigZag causal en 1m (giro de 2,5 ATR) y tramo >= IMPULSE_ATR ATR, a favor de
   la tendencia Supertrend 10/3 de 15m Y de 1h (velas cerradas).
2. Entrada (2 variantes): orden limitada en 0,618, o confirmacion = el precio toca
   0,618 y una vela 1m CIERRA de vuelta por encima de 0,5 (compra; espejo para venta).
3. Stop: bajo 0,786 (estructura) con tope de $2,50, o fijo $2,50.
4. Objetivo: nivel 0 (extremo del impulso) o extension 1,272 / 1,618.
5. Stop a cero: sin, al avanzar +0,5R o +1R (el stop pasa a entrada + costo).
6. Conservador: si una vela toca stop y objetivo cuenta el stop; el stop a cero se
   activa recien en la vela siguiente. Costo (spread) $0,30/oz; sensibilidad a $0,60.

Seleccion: la configuracion se elige con la 1.a mitad de los datos (entrenamiento) y se
mide en la 2.a mitad (prueba). Cuenta: $10, riesgo % por operacion, apalancamiento 1:200.
"""
from __future__ import annotations

import itertools
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "oro_dashboard"))
sys.path.insert(0, str(ROOT / "research" / "backtest_1m"))
from core.supertrend import rma_atr  # noqa: E402
from backtest_1m import htf_trend, tradable_mask  # noqa: E402

ZZ_ATR, IMPULSE_ATR, SETUP_BARS, MAX_HOLD = 2.5, 5.0, 60, 240
STOP_CAP = 2.50
NY = "America/New_York"


def load() -> pd.DataFrame:
    p = Path(__file__).resolve().parent / ".cache" / "GC_F_1m.pkl"
    df = pd.read_pickle(p)
    df.index = pd.DatetimeIndex(df.index).tz_convert("UTC")
    return df


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


def simulate(df, F, entry_mode, stop_mode, target_mode, be_r, cost=0.30):
    o, h, l, c = (df[k].to_numpy() for k in ("open", "high", "low", "close"))
    atr, t15, t60, ok = F["atr"], F["t15"], F["t60"], F["ok"]
    imps = {i: (a, b, s) for i, a, b, s in impulses(h, l, atr)}
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
        lv = lambda r: b - s * r * leg  # nivel de retroceso r
        z50, z618, z786 = lv(0.5), lv(0.618), lv(0.786)
        j, entry_i, px, touched = i + 1, None, None, False
        while j < min(n - 1, i + 1 + SETUP_BARS):
            if (s == 1 and (h[j] > b or l[j] < a)) or (s == -1 and (l[j] < b or h[j] > a)):
                break  # siguio sin retroceder, o rompio el origen: setup invalido
            hit618 = (s == 1 and l[j] <= z618) or (s == -1 and h[j] >= z618)
            if entry_mode == "limite 0,618" and hit618 and ok[j]:
                entry_i, px = j, (min(z618, o[j]) if s == 1 else max(z618, o[j]))
                break
            touched |= hit618
            if entry_mode == "confirmacion" and touched and ((s == 1 and c[j] > z50) or (s == -1 and c[j] < z50)) and ok[j + 1]:
                entry_i, px = j + 1, o[j + 1]
                break
            j += 1
        if entry_i is None:
            i = j + 1
            continue
        stop = px - s * STOP_CAP if stop_mode == "fijo $2,50" else (
            max(z786 - 0.20, px - STOP_CAP) if s == 1 else min(z786 + 0.20, px + STOP_CAP))
        target = {"nivel 0": b, "ext 1,272": b + s * 0.272 * leg, "ext 1,618": b + s * 0.618 * leg}[target_mode]
        risk = s * (px - stop)
        if risk <= 0.05 or s * (target - px) <= 0:
            i = entry_i + 1
            continue
        k, exit_px, be_on = entry_i, None, False
        while k < n:
            if not ok[k] or k - entry_i > MAX_HOLD:
                exit_px = o[k]
                break
            if (s == 1 and l[k] <= stop) or (s == -1 and h[k] >= stop):
                exit_px = (min(stop, o[k]) if s == 1 else max(stop, o[k])) if k > entry_i else stop
                break
            if k > entry_i and ((s == 1 and h[k] >= target) or (s == -1 and l[k] <= target)):
                exit_px = target
                break
            if be_r and not be_on and s * ((h[k] if s == 1 else l[k]) - px) >= be_r * risk:
                stop, be_on = px + s * cost, True  # stop a cero (+ costo) desde la vela siguiente
            k += 1
        if exit_px is None:
            exit_px, k = c[-1], n - 1
        pnl = s * (exit_px - px) - cost
        trades.append({"i": entry_i, "time": df.index[entry_i], "side": s, "px": px, "risk": risk + cost,
                       "pnl": pnl, "R": pnl / (risk + cost), "be": be_on})
        i = k + 1
    return pd.DataFrame(trades)


def equity(trades: pd.DataFrame, risk_pct: float, lev=200.0, start=10.0):
    eq, peak, mdd, path = start, start, 0.0, []
    for t in trades.itertuples():
        size = min(eq * risk_pct / t.risk, eq * lev / t.px)
        size = np.floor(size / 0.01 + 1e-9) * 0.01
        if size < 0.01:
            break
        eq = max(eq + size * t.pnl, 0.0)
        peak, mdd = max(peak, eq), max(mdd, 1 - eq / peak if peak else 0)
        path.append((t.time, eq))
    return eq, mdd, path


def stats(tr: pd.DataFrame):
    if tr.empty:
        return {"n": 0}
    r = tr["pnl"].to_numpy()
    return {"n": len(r), "win": (r > 0).mean(), "exp": r.mean(), "R": tr["R"].mean(),
            "pf": r[r > 0].sum() / -r[r <= 0].sum() if (r <= 0).any() else np.inf}


def main():
    df = load()
    ok = tradable_mask(df.index)
    F = {"atr": rma_atr(df.high.to_numpy(), df.low.to_numpy(), df.close.to_numpy(), 14),
         "t15": htf_trend(df, 15), "t60": htf_trend(df, 60), "ok": ok}
    half_time = df.index[len(df) // 2]
    rows = []
    for em, sm, tm, be in itertools.product(("limite 0,618", "confirmacion"), ("estructura (tope $2,50)", "fijo $2,50"),
                                            ("nivel 0", "ext 1,272", "ext 1,618"), (None, 0.5, 1.0)):
        tr = simulate(df, F, em, sm, tm, be)
        if tr.empty:
            continue
        rows.append({"cfg": (em, sm, tm, be), "tr": tr, "train": stats(tr[tr.time < half_time]),
                     "test": stats(tr[tr.time >= half_time])})
    print(f"Datos: {len(df):,} velas 1m GC=F {df.index[0]:%d/%m} -> {df.index[-1]:%d/%m/%Y} · entrenamiento hasta {half_time:%d/%m %H:%M} UTC")
    print(f"{len(rows)} configuraciones · ganan en entrenamiento: {sum(r['train'].get('exp', -1) > 0 for r in rows)} · "
          f"ganan en prueba: {sum(r['test'].get('exp', -1) > 0 for r in rows)} · ganan en ambas: "
          f"{sum(r['train'].get('exp', -1) > 0 and r['test'].get('exp', -1) > 0 for r in rows)}")
    rows = [r for r in rows if r["train"].get("n", 0) >= 20]
    rows.sort(key=lambda r: r["train"]["exp"] * np.sqrt(r["train"]["n"]), reverse=True)
    print("\nTop 5 elegidas SOLO con entrenamiento -> como les fue en la PRUEBA:")
    print("entrada | stop | objetivo | stop a cero | ent: ops/acierto/$oz | PRUEBA: ops/acierto/$oz/PF | prueba con costo $0,60")
    for r in rows[:5]:
        em, sm, tm, be = r["cfg"]
        a, t = r["train"], r["test"]
        t60c = stats(simulate(df, F, em, sm, tm, be, cost=0.60).pipe(lambda x: x[x.time >= half_time]))
        print(f"{em} | {sm} | {tm} | {'no' if be is None else f'+{be}R'} | {a['n']}/{a['win']*100:.0f}%/{a['exp']:+.2f} | "
              f"{t.get('n',0)}/{t.get('win',0)*100:.0f}%/{t.get('exp',0):+.2f}/{t.get('pf',0):.2f} | {t60c.get('exp',0):+.2f}")
    best = rows[0]
    tr = best["tr"]
    print(f"\nMejor por entrenamiento: {best['cfg']}")
    test_tr = tr[tr.time >= half_time]
    for rp in (0.02, 0.05, 0.10, 0.30):
        eqf, mdd, _ = equity(tr, rp)
        eqt, mddt, _ = equity(test_tr, rp)
        print(f"  riesgo {rp*100:.0f}% por op (1:200): $10 en 28 dias -> ${eqf:,.2f} (caida max {mdd*100:.0f}%) · solo en la prueba -> ${eqt:,.2f} (caida {mddt*100:.0f}%)")
    d1920 = tr[(tr.time >= "2026-11-19") & (tr.time < "2026-11-21")]
    print(f"  dias 19-20/11 (cuando operaste): {len(d1920)} ops, acierto {(d1920.pnl>0).mean()*100 if len(d1920) else 0:.0f}%, "
          f"{d1920.pnl.sum():+.2f} $/oz; $10 al 10% -> ${equity(d1920, 0.10)[0]:,.2f}")
    rng = np.random.default_rng(19)
    R = test_tr["R"].to_numpy() if len(test_tr) >= 20 else tr["R"].to_numpy()
    per_day = len(tr) / max(1, df.index.normalize().nunique())
    n30 = int(per_day * 21)
    for rp in (0.02, 0.05, 0.10, 0.30):
        eq = np.full(10000, 10.0)
        hit = np.zeros(10000, bool)
        for _ in range(n30):
            eq = np.maximum(eq * (1 + rp * rng.choice(R, 10000)), 0)
            hit |= eq >= 135
        print(f"  Monte Carlo 1 mes ({n30} ops, riesgo {rp*100:.0f}%): mediana ${np.median(eq):,.2f} · P(llegar a $135) {hit.mean()*100:.0f}% · "
              f"P(terminar < $5) {(eq < 5).mean()*100:.0f}%")


if __name__ == "__main__":
    main()
