"""Laboratorio de backtesting en 1 minuto para el oro (PAXG-USD y GC=F, Yahoo Finance).

Objetivo: buscar una tecnica estadistica rentable DESPUES de costos en 1m y medir su
riesgo real, sin enganarse con el sobreajuste.

Metodologia (anti-sobreajuste):
- Datos: los ~28 dias de velas 1m que Yahoo permite (limite: ultimos 30 dias).
- Solo se opera con el oro spot abierto (sin fin de semana ni pausa diaria 17-18 h NY):
  PAXG cotiza 24/7 pero el CFD GOLD de Capital.com no.
- Division cronologica: 60 % entrenamiento, 20 % validacion, 20 % PRUEBA. Los parametros
  se eligen SOLO con entrenamiento (+ confirmacion en validacion). La prueba se mira una
  sola vez, al final, para el reporte.
- Señal al cierre de la vela i, entrada a la APERTURA de la vela i+1. Si una vela toca
  stop y objetivo a la vez, cuenta como stop (conservador).
- Costo por operacion (spread + deslizamiento, USD por onza) descontado en cada trade;
  se reporta la sensibilidad a 0 / 0.30 / 0.60.
- Monte Carlo (bootstrap de dias) para la probabilidad de perder en un mes y la caida
  maxima esperada.

Uso:  python research/backtest_1m/backtest_1m.py [--cache DIR]
"""
from __future__ import annotations

import argparse
import itertools
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "oro_dashboard"))
from core.supertrend import rma_atr, supertrend  # noqa: E402

NY = "America/New_York"
BASE_COST = 0.30
COSTS = (0.0, 0.30, 0.60)
SPLITS = (0.6, 0.2, 0.2)
RNG = np.random.default_rng(19)


# ---------------------------------------------------------------- datos

def download(symbol: str, cache: Path) -> pd.DataFrame:
    path = cache / f"{symbol.replace('=', '_')}_1m.pkl"
    if path.exists():
        return pd.read_pickle(path)
    import yfinance as yf
    parts, end = [], pd.Timestamp.now(tz="UTC").floor("min")
    for _ in range(5):
        start = end - pd.Timedelta(days=7)
        r = yf.download(symbol, start=start.tz_localize(None), end=end.tz_localize(None), interval="1m",
                        progress=False, auto_adjust=True)
        end = start
        if r is None or r.empty:
            continue
        r.columns = r.columns.get_level_values(0)
        parts.append(r)
    d = pd.concat(parts).sort_index()
    d = d[~d.index.duplicated()].rename(columns=str.lower)[["open", "high", "low", "close"]].dropna()
    d.index = pd.DatetimeIndex(d.index).tz_convert("UTC")
    d.to_pickle(path)
    return d


def tradable_mask(index: pd.DatetimeIndex) -> np.ndarray:
    """Oro spot abierto: dom 18:00 -> vie 17:00 NY, sin la pausa diaria 17:00-18:00."""
    ny = index.tz_convert(NY)
    wd, hr = ny.weekday, ny.hour
    closed = (wd == 5) | ((wd == 4) & (hr >= 17)) | ((wd == 6) & (hr < 18)) | (hr == 17)
    return ~np.asarray(closed)


# ---------------------------------------------------------------- motor

@dataclass
class Trade:
    entry_i: int
    exit_i: int
    side: int
    entry: float
    exit: float
    pnl_gross: float


def run_engine(df: pd.DataFrame, sig: np.ndarray, tradable: np.ndarray, atr: np.ndarray,
               sl_atr: float | None, tp_atr: float | None, max_bars: int | None,
               exit_on_flip: bool = False, flip_sig: np.ndarray | None = None,
               lo: int = 0, hi: int | None = None) -> list[Trade]:
    """Una posicion a la vez. Entrada a la apertura siguiente; stop primero si ambos."""
    o, h, l, c = (df[k].to_numpy() for k in ("open", "high", "low", "close"))
    hi = len(df) - 1 if hi is None else hi
    trades: list[Trade] = []
    i = lo
    while i < hi - 1:
        s = sig[i]
        if s == 0 or not tradable[i + 1] or not np.isfinite(atr[i]):
            i += 1
            continue
        e_i = i + 1
        entry = o[e_i]
        stop = entry - s * sl_atr * atr[i] if sl_atr else None
        tgt = entry + s * tp_atr * atr[i] if tp_atr else None
        exit_px, exit_i = None, None
        j = e_i
        while j < hi:
            if not tradable[j]:                       # cierre de mercado: salir a la apertura de esa vela
                exit_px, exit_i = o[j], j
                break
            if stop is not None and ((s == 1 and l[j] <= stop) or (s == -1 and h[j] >= stop)):
                exit_px, exit_i = (min(stop, o[j]) if s == 1 else max(stop, o[j])), j  # gap peor que el stop
                break
            if tgt is not None and ((s == 1 and h[j] >= tgt) or (s == -1 and l[j] <= tgt)):
                exit_px, exit_i = tgt, j
                break
            if exit_on_flip and flip_sig is not None and flip_sig[j] == -s and j + 1 < hi:
                exit_px, exit_i = o[j + 1], j + 1
                break
            if max_bars and j - e_i + 1 >= max_bars and j + 1 < hi:
                exit_px, exit_i = o[j + 1], j + 1
                break
            j += 1
        if exit_px is None:
            exit_px, exit_i = c[hi - 1], hi - 1
        trades.append(Trade(e_i, exit_i, int(s), entry, exit_px, s * (exit_px - entry)))
        i = exit_i if exit_on_flip else exit_i + 0  # siguiente señal desde la salida
        if exit_on_flip and flip_sig is not None and flip_sig[exit_i - 1] == -s:
            i = exit_i - 1  # en estrategias de vuelta, la señal contraria abre de inmediato
    return trades


def metrics(trades: list[Trade], df: pd.DataFrame, cost: float) -> dict:
    if not trades:
        return {"n": 0}
    pnl = np.array([t.pnl_gross for t in trades]) - cost
    days = pd.DatetimeIndex(df.index[[t.exit_i for t in trades]]).tz_convert(NY).date
    daily = pd.Series(pnl).groupby(np.asarray(days)).sum()
    eq = np.cumsum(pnl)
    wins, losses = pnl[pnl > 0], pnl[pnl <= 0]
    boot = RNG.choice(pnl, size=(2000, len(pnl)), replace=True).mean(axis=1)
    return {
        "n": int(len(pnl)), "win_rate": float((pnl > 0).mean()),
        "pf": float(wins.sum() / -losses.sum()) if losses.sum() < 0 else float("inf"),
        "exp": float(pnl.mean()), "exp_ci_lo": float(np.percentile(boot, 2.5)),
        "exp_ci_hi": float(np.percentile(boot, 97.5)), "p_exp_le_0": float((boot <= 0).mean()),
        "net": float(pnl.sum()), "max_dd": float((np.maximum.accumulate(eq) - eq).max()),
        "avg_win": float(wins.mean()) if len(wins) else 0.0, "avg_loss": float(losses.mean()) if len(losses) else 0.0,
        "green_days": float((daily > 0).mean()), "n_days": int(len(daily)),
        "avg_bars": float(np.mean([t.exit_i - t.entry_i + 1 for t in trades])),
        "pnl": pnl, "daily": daily,
    }


# ---------------------------------------------------------------- features / señales

def htf_trend(df: pd.DataFrame, minutes: int, period=10, factor=3.0) -> np.ndarray:
    """Tendencia Supertrend de una temporalidad mayor, alineada SIN mirar el futuro:
    cada vela 1m ve solo la ultima vela mayor ya cerrada."""
    r = df.resample(f"{minutes}min", label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
    st = supertrend(r, period, factor)["trend"]
    st.index = st.index + pd.Timedelta(minutes=minutes)  # disponible al cierre
    return st.reindex(df.index, method="ffill").fillna(0).to_numpy()


def feature_matrix(df: pd.DataFrame) -> pd.DataFrame:
    c = df["close"]
    lr = np.log(c).diff()
    vol = lr.rolling(60, min_periods=30).std()
    f = {}
    for k in (1, 3, 5, 15, 30, 60):
        f[f"r{k}"] = (np.log(c) - np.log(c.shift(k))) / (vol * np.sqrt(k))
    for n in (20, 60, 240):
        m, s = c.rolling(n).mean(), c.rolling(n).std()
        f[f"z{n}"] = (c - m) / s
    delta = c.diff()
    up = delta.clip(lower=0).ewm(alpha=1 / 14, adjust=False).mean()
    dn = (-delta.clip(upper=0)).ewm(alpha=1 / 14, adjust=False).mean()
    f["rsi"] = (100 - 100 / (1 + up / dn.replace(0, np.nan)) - 50) / 50
    f["volr"] = np.log(vol / vol.rolling(1440, min_periods=240).median())
    ny = df.index.tz_convert(NY)
    ang = 2 * np.pi * (ny.hour * 60 + ny.minute) / 1440
    f["hs"], f["hc"] = np.sin(ang), np.cos(ang)
    f["t15"] = htf_trend(df, 15)
    f["t60"] = htf_trend(df, 60)
    return pd.DataFrame(f, index=df.index).clip(-6, 6)


def logistic_fit(X, y, lam=1.0, iters=30):
    p = X.shape[1]
    b = np.zeros(p)
    P = lam * np.eye(p)
    P[-1, -1] = 0
    for _ in range(iters):
        z = np.clip(X @ b, -30, 30)
        pr = 1 / (1 + np.exp(-z))
        w = pr * (1 - pr)
        g = X.T @ (pr - y) + P @ b
        H = (X * w[:, None]).T @ X + P + 1e-9 * np.eye(p)
        step = np.linalg.solve(H, g)
        b -= step
        if np.abs(step).max() < 1e-7:
            break
    return b


def ml_signals(df, F, horizon, threshold, cost, split_train, retrain_every=1440):
    """Regresion logistica walk-forward: P(retorno a `horizon` min > costo). Se reentrena
    cada dia SOLO con datos pasados (expanding window). Opera si P > threshold."""
    c = df["close"].to_numpy()
    fut = np.full(len(c), np.nan)
    fut[:-horizon] = c[horizon:] - c[:-horizon]
    X_all = F.to_numpy()
    ok = np.isfinite(X_all).all(1)
    sig = np.zeros(len(c), dtype=int)
    prob = np.full(len(c), np.nan)
    start = split_train
    for s0 in range(start, len(c), retrain_every):
        tr = np.flatnonzero(ok[: s0 - horizon] & np.isfinite(fut[: s0 - horizon]))
        if len(tr) < 2000:
            continue
        Xt = X_all[tr]
        mu, sd = Xt.mean(0), Xt.std(0)
        sd[sd == 0] = 1
        A = np.column_stack([(Xt - mu) / sd, np.ones(len(tr))])
        b_up = logistic_fit(A, (fut[tr] > cost).astype(float))
        b_dn = logistic_fit(A, (fut[tr] < -cost).astype(float))
        idx = np.arange(s0, min(s0 + retrain_every, len(c)))
        idx = idx[ok[idx]]
        B = np.column_stack([(X_all[idx] - mu) / sd, np.ones(len(idx))])
        pu, pd_ = 1 / (1 + np.exp(-B @ b_up)), 1 / (1 + np.exp(-B @ b_dn))
        prob[idx] = pu - pd_
        sig[idx[(pu > threshold) & (pu > pd_)]] = 1
        sig[idx[(pd_ > threshold) & (pd_ > pu)]] = -1
    return sig, prob


# ---------------------------------------------------------------- estrategias

def strategy_space(df, F, atr):
    """Genera (nombre, params, kwargs del motor) para cada familia."""
    c, h, l = df["close"], df["high"], df["low"]
    out = []
    # 1) Supertrend flip 1m (la regla del robot llevada a 1 minuto)
    for period, factor in itertools.product((10, 20), (3.0, 5.0)):
        st = supertrend(df, period, factor)
        sig = np.where(st["buy"], 1, np.where(st["sell"], -1, 0))
        out.append(("Supertrend flip 1m", f"{period}/{factor:g}",
                    dict(sig=sig, sl_atr=None, tp_atr=None, max_bars=None, exit_on_flip=True, flip_sig=sig)))
        # 2) mismo, pero solo a favor de la tendencia de 15m y 1h
        filt = np.where((sig == np.sign(F["t15"].to_numpy())) & (sig == np.sign(F["t60"].to_numpy())), sig, 0)
        out.append(("Supertrend 1m + filtro 15m/1h", f"{period}/{factor:g}",
                    dict(sig=filt, sl_atr=None, tp_atr=None, max_bars=None, exit_on_flip=True, flip_sig=sig)))
    # 3) Reversion a la media (z-score) con stop/objetivo en ATR
    for n, k, tp, sl in itertools.product((20, 60), (2.0, 2.5, 3.0), (1.0, 2.0), (1.5, 3.0)):
        z = F[f"z{n}"].to_numpy()
        sig = np.where(z < -k, 1, np.where(z > k, -1, 0))
        out.append(("Reversion z-score", f"n{n} z{k:g} tp{tp:g} sl{sl:g}",
                    dict(sig=sig, sl_atr=sl, tp_atr=tp, max_bars=60, exit_on_flip=False, flip_sig=None)))
    # 4) Ruptura de rango (Donchian) a favor de 15m
    for n, tp, sl in itertools.product((30, 60, 120), (2.0, 4.0), (1.0, 2.0)):
        up = (c > h.shift(1).rolling(n).max()).to_numpy()
        dn = (c < l.shift(1).rolling(n).min()).to_numpy()
        t15 = F["t15"].to_numpy()
        sig = np.where(up & (t15 == 1), 1, np.where(dn & (t15 == -1), -1, 0))
        out.append(("Ruptura Donchian + 15m", f"n{n} tp{tp:g} sl{sl:g}",
                    dict(sig=sig, sl_atr=sl, tp_atr=tp, max_bars=120, exit_on_flip=False, flip_sig=None)))
    # 5) "Trampa de alto acierto": objetivo chico, stop grande (para mostrar el efecto)
    for tp, sl in ((0.3, 3.0), (0.5, 4.0)):
        z = F["z60"].to_numpy()
        sig = np.where(z < -2, 1, np.where(z > 2, -1, 0))
        out.append(("Alto acierto (TP chico / SL grande)", f"tp{tp:g} sl{sl:g}",
                    dict(sig=sig, sl_atr=sl, tp_atr=tp, max_bars=240, exit_on_flip=False, flip_sig=None)))
    return out


# ---------------------------------------------------------------- monte carlo

def monte_carlo_days(daily: pd.Series, days=20, sims=10000) -> dict:
    vals = daily.to_numpy()
    if len(vals) < 3:
        return {}
    draws = RNG.choice(vals, size=(sims, days), replace=True)
    tot = draws.sum(1)
    eq = np.cumsum(draws, axis=1)
    dd = (np.maximum.accumulate(np.maximum(eq, 0), axis=1) - eq).max(1)
    return {"p_loss_month": float((tot < 0).mean()), "median_month": float(np.median(tot)),
            "p5_month": float(np.percentile(tot, 5)), "p95_month": float(np.percentile(tot, 95)),
            "dd95": float(np.percentile(dd, 95))}


# ---------------------------------------------------------------- main

def evaluate(symbol: str, cache: Path) -> dict:
    df = download(symbol, cache)
    tradable = tradable_mask(df.index)
    atr = rma_atr(df["high"].to_numpy(), df["low"].to_numpy(), df["close"].to_numpy(), 14)
    F = feature_matrix(df)
    n = len(df)
    a, b = int(n * SPLITS[0]), int(n * (SPLITS[0] + SPLITS[1]))
    segs = {"train": (300, a), "val": (a, b), "test": (b, n - 1)}
    rows = []
    for fam, params, kw in strategy_space(df, F, atr):
        res = {}
        for seg, (lo, hi) in segs.items():
            tr = run_engine(df, tradable=tradable, atr=atr, lo=lo, hi=hi, **kw)
            res[seg] = metrics(tr, df, BASE_COST)
        rows.append((fam, params, kw, res))
    # ML logistico walk-forward (se entrena con el pasado; train = calentamiento)
    for horizon, thr in itertools.product((5, 15, 30), (0.55, 0.60, 0.65)):
        sig, _ = ml_signals(df, F, horizon, thr, BASE_COST, split_train=segs["train"][1] // 2)
        kw = dict(sig=sig, sl_atr=2.0, tp_atr=None, max_bars=horizon, exit_on_flip=False, flip_sig=None)
        res = {seg: metrics(run_engine(df, tradable=tradable, atr=atr, lo=lo, hi=hi, **kw), df, BASE_COST)
               for seg, (lo, hi) in segs.items()}
        rows.append(("Regresion logistica (walk-forward)", f"h{horizon} p>{thr:.2f}", kw, res))

    # Seleccion: SOLO con entrenamiento -> mejor de cada familia (min 30 trades, exp > 0)
    best = {}
    for fam, params, kw, res in rows:
        r = res["train"]
        if r.get("n", 0) < 30:
            continue
        score = r["exp"] * np.sqrt(r["n"])  # t-stat aproximado: premia ventaja Y muestra
        if fam not in best or score > best[fam][0]:
            best[fam] = (score, params, kw, res)
    out = {"symbol": symbol, "bars": n, "from": df.index[0], "to": df.index[-1],
           "atr_med": float(np.nanmedian(atr)), "segs": {k: (df.index[v[0]], df.index[v[1] - 1]) for k, v in segs.items()},
           "families": {}}
    for fam, (score, params, kw, res) in best.items():
        lo, hi = segs["test"]
        sens = {}
        for cost in COSTS:
            sens[cost] = metrics(run_engine(df, tradable=tradable, atr=atr, lo=lo, hi=hi, **kw), df, cost)["exp"]
        # Monte Carlo con los dias de validacion + prueba (fuera del ajuste)
        oos = pd.concat([res["val"].get("daily", pd.Series(dtype=float)), res["test"].get("daily", pd.Series(dtype=float))])
        out["families"][fam] = {"params": params, "res": res, "cost_sens": sens, "mc": monte_carlo_days(oos)}
    out["n_configs"] = len(rows)
    return out


def fmt(x, pct=False, money=False):
    if x is None or (isinstance(x, float) and not np.isfinite(x)):
        return "—"
    if pct:
        return f"{x * 100:.0f} %"
    if money:
        return f"{x:+.2f}"
    return f"{x:.2f}"


def report(results: list[dict]) -> str:
    L = ["# Backtesting 1 minuto — oro", ""]
    for R in results:
        L += [f"## {R['symbol']}  ({R['bars']:,} velas 1m, {R['from']:%d/%m} → {R['to']:%d/%m/%Y}, "
              f"ATR 1m mediano ${R['atr_med']:.2f}, {R['n_configs']} configuraciones probadas)", ""]
        L += ["Segmentos: " + ", ".join(f"{k} {a:%d/%m %H:%M}–{b:%d/%m %H:%M}" for k, (a, b) in R["segs"].items()), ""]
        L += ["| Familia (mejor en entrenamiento) | Parametros | Trades ent/val/PRUEBA | Acierto PRUEBA | PF PRUEBA | "
              "$/trade PRUEBA (IC 95 %) | Neto PRUEBA $/oz | Caida max PRUEBA | Dias verdes PRUEBA | $/trade con costo 0 / 0.30 / 0.60 |",
              "|---|---|---|---|---|---|---|---|---|---|"]
        for fam, F in R["families"].items():
            r, t = F["res"], F["res"]["test"]
            if t.get("n", 0) == 0:
                L.append(f"| {fam} | {F['params']} | {r['train']['n']}/{r['val'].get('n', 0)}/0 | — | — | — | — | — | — | — |")
                continue
            s = F["cost_sens"]
            L.append(
                f"| {fam} | {F['params']} | {r['train']['n']}/{r['val'].get('n', 0)}/{t['n']} | {fmt(t['win_rate'], pct=True)} | "
                f"{fmt(t['pf'])} | {fmt(t['exp'], money=True)} ({fmt(t['exp_ci_lo'], money=True)} a {fmt(t['exp_ci_hi'], money=True)}) | "
                f"{fmt(t['net'], money=True)} | {fmt(t['max_dd'])} | {fmt(t['green_days'], pct=True)} | "
                f"{fmt(s[0.0], money=True)} / {fmt(s[0.30], money=True)} / {fmt(s[0.60], money=True)} |")
        L += ["", "Entrenamiento vs prueba ($/trade con costo 0.30):", ""]
        for fam, F in R["families"].items():
            r = F["res"]
            L.append(f"- {fam}: entrenamiento {fmt(r['train'].get('exp'), money=True)} · validacion "
                     f"{fmt(r['val'].get('exp'), money=True)} · prueba {fmt(r['test'].get('exp'), money=True)} · "
                     f"Monte Carlo 20 dias (val+prueba): P(perder) {fmt(F['mc'].get('p_loss_month'), pct=True)}, "
                     f"caida 95 % {fmt(F['mc'].get('dd95'))}")
        L.append("")
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", default=str(Path(__file__).resolve().parent / ".cache"))
    ap.add_argument("--out", default=str(Path(__file__).resolve().parent / "resultados.md"))
    a = ap.parse_args()
    cache = Path(a.cache)
    cache.mkdir(parents=True, exist_ok=True)
    results = [evaluate(sym, cache) for sym in ("PAXG-USD", "GC=F")]
    text = report(results)
    Path(a.out).write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
