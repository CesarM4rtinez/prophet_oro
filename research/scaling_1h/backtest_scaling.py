"""Backtest 1h (2 años) del Supertrend 10/3 con tamaño adaptable al capital.

Compara, sobre la MISMA señal (Supertrend 10/3 en velas 1h cerradas):
  A. Actual: 0.1 oz fijo, siempre en mercado.
  B. Riesgo fijo: cada posicion arriesga un % del capital (el tamaño crece con la cuenta).
  C. B + piramidacion: agrega posiciones a favor de la tendencia, hasta N segun el
     capital, con el riesgo TOTAL repartido entre las N (riesgo equilibrado).
  D. C + solo entra en el cambio de color (no a mitad de tendencia).
  E. D + frenos: limite de perdida diaria y pausa por caida maxima.

Reglas comunes (ejecucion realista): señal al cierre de la vela 1h, ejecucion a la
apertura de la siguiente; stop de cada posicion = linea Supertrend -/+ 1 ATR (solo se
mueve a favor); si la apertura salta el stop se ejecuta a la apertura (gap); costo
de $0.30/oz por operacion; tamaño minimo 0.01 oz; apalancamiento maximo 1:20 sobre
como mucho el 50 % del capital (margen). Solo velas con el oro spot abierto.

Uso: python research/scaling_1h/backtest_scaling.py
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "oro_dashboard"))
sys.path.insert(0, str(ROOT / "robot_supertrend"))
from core.supertrend import rma_atr, supertrend  # noqa: E402
from risk import RiskConfig, max_units_for_equity  # noqa: E402  (mismo modulo que el robot)

NY = "America/New_York"
COST = 0.30
START = 10_000.0


def load(symbol: str, cache: Path) -> pd.DataFrame:
    path = cache / f"{symbol.replace('=', '_')}_1h.pkl"
    if path.exists():
        return pd.read_pickle(path)
    import yfinance as yf
    r = yf.download(symbol, period="730d", interval="60m", progress=False, auto_adjust=True)
    r.columns = r.columns.get_level_values(0)
    d = r.rename(columns=str.lower)[["open", "high", "low", "close"]].dropna()
    d.index = pd.DatetimeIndex(d.index).tz_convert("UTC")
    ny = d.index.tz_convert(NY)
    wd, hr = ny.weekday, ny.hour
    closed = (wd == 5) | ((wd == 4) & (hr >= 17)) | ((wd == 6) & (hr < 18))
    d = d[~np.asarray(closed)]
    d.to_pickle(path)
    return d


@dataclass
class Unit:
    side: int
    entry: float
    size: float
    stop: float


@dataclass
class Variant:
    name: str
    fixed_size: float | None = None     # A
    pyramid: bool = False               # C
    fresh_only: bool = False            # D
    breakers: bool = False              # E
    cfg: RiskConfig = field(default_factory=RiskConfig)


def simulate(df: pd.DataFrame, v: Variant) -> dict:
    o, h, l, c = (df[k].to_numpy() for k in ("open", "high", "low", "close"))
    st = supertrend(df, 10, 3.0)
    trend, line = st["trend"].to_numpy(), st["supertrend"].to_numpy()
    flip = (st["buy"] | st["sell"]).to_numpy()
    atr = rma_atr(h, l, c, 10)
    days = df.index.tz_convert(NY).normalize()
    cfg = v.cfg
    eq, peak = START, START
    units: list[Unit] = []
    trades, curve = [], []
    day, day_start_eq, paused_day, halted = None, START, False, False

    def size_for(entry, stop, equity, n_max):
        risk_cash = equity * cfg.total_risk_pct / 100 / n_max
        dist = abs(entry - stop) + COST
        sz = np.floor(risk_cash / dist / cfg.size_step) * cfg.size_step
        # margen: nocional total <= capital * margen_max * apalancamiento
        open_notional = sum(u.size for u in units) * entry
        cap = (equity * cfg.max_margin_pct / 100 * cfg.leverage - open_notional) / entry
        sz = min(sz, np.floor(max(cap, 0) / cfg.size_step) * cfg.size_step)
        return sz if sz >= cfg.min_size else 0.0

    def close_unit(u, px):
        nonlocal eq
        pnl = u.side * (px - u.entry) * u.size - COST * u.size
        eq += pnl
        trades.append(pnl)

    for i in range(20, len(df) - 1):
        # 1) stops intrabar en la vela i (ya abierta con la decision de i-1)
        for u in list(units):
            if (u.side == 1 and l[i] <= u.stop) or (u.side == -1 and h[i] >= u.stop):
                px = min(u.stop, o[i]) if u.side == 1 else max(u.stop, o[i])
                close_unit(u, px)
                units.remove(u)
        # 2) contabilidad diaria / frenos
        if days[i] != day:
            day, day_start_eq, paused_day = days[i], eq, False
        mtm = eq + sum(u.side * (c[i] - u.entry) * u.size for u in units)
        peak = max(peak, mtm)
        curve.append(mtm)
        if v.breakers:
            if mtm < day_start_eq * (1 - cfg.daily_loss_pct / 100):
                paused_day = True
            if mtm < peak * (1 - cfg.max_drawdown_pct / 100):
                halted = True
        can_enter = not (v.breakers and (paused_day or halted))
        if not np.isfinite(atr[i]) or trend[i] == 0:
            continue
        side = int(trend[i])
        stop_new = line[i] - side * cfg.stop_atr * atr[i]
        # 3) cambio de color -> cerrar todo a la apertura siguiente
        if units and units[0].side != side:
            for u in units:
                close_unit(u, o[i + 1])
            units = []
        # 4) mover stops a favor
        for u in units:
            u.stop = max(u.stop, stop_new) if side == 1 else min(u.stop, stop_new)
        entry = o[i + 1]
        if (side == 1 and entry <= stop_new) or (side == -1 and entry >= stop_new):
            continue
        if not units:
            if v.fresh_only and not flip[i]:
                continue
            if not can_enter:
                continue
            if v.fixed_size:
                units.append(Unit(side, entry, v.fixed_size, stop_new))
            else:
                n_max = max_units_for_equity(eq, cfg) if v.pyramid else 1
                sz = size_for(entry, stop_new, eq, n_max)
                if sz > 0:
                    units.append(Unit(side, entry, sz, stop_new))
        elif v.pyramid and can_enter:
            n_max = max_units_for_equity(eq, cfg)
            last = units[-1]
            moved = side * (c[i] - last.entry) >= cfg.add_every_atr * atr[i]
            open_risk = sum(abs(u.entry - u.stop) * u.size for u in units if side * (u.stop - u.entry) < 0)
            if len(units) < n_max and moved and open_risk <= eq * cfg.total_risk_pct / 100:
                sz = size_for(entry, stop_new, eq, n_max)
                if sz > 0:
                    units.append(Unit(side, entry, sz, stop_new))
    for u in units:
        close_unit(u, c[-1])
    curve = np.array(curve)
    tr = np.array(trades)
    dd = (np.maximum.accumulate(curve) - curve) / np.maximum.accumulate(curve)
    monthly = pd.Series(curve, index=df.index[20:20 + len(curve)]).resample("ME").last().pct_change().dropna()
    rets = pd.Series(curve).pct_change().dropna()
    return {
        "final": eq, "ret": eq / START - 1, "max_dd": float(dd.max()), "trades": int(len(tr)),
        "win": float((tr > 0).mean()) if len(tr) else np.nan,
        "pf": float(tr[tr > 0].sum() / -tr[tr <= 0].sum()) if (tr <= 0).any() else np.inf,
        "worst_month": float(monthly.min()), "pos_months": float((monthly > 0).mean()),
        "sharpe": float(rets.mean() / rets.std() * np.sqrt(24 * 252)) if rets.std() > 0 else np.nan,
        "trades_arr": tr,
    }


def mc_month_loss(tr: np.ndarray, per_month: float, sims=10000) -> float:
    rng = np.random.default_rng(19)
    k = max(1, int(round(per_month)))
    return float((rng.choice(tr, size=(sims, k)).sum(1) < 0).mean())


def main():
    cache = Path(__file__).resolve().parent / ".cache"
    cache.mkdir(exist_ok=True)
    variants = [
        Variant("A. Actual: 0,1 oz fijo, siempre en mercado", fixed_size=0.1),
        Variant("B. Riesgo fijo por operacion (1 posicion)"),
        Variant("C. B + piramidacion segun capital", pyramid=True),
        Variant("D. C + solo en el cambio de color", pyramid=True, fresh_only=True),
        Variant("E. D + frenos (perdida diaria / caida max)", pyramid=True, fresh_only=True, breakers=True),
    ]
    lines = ["# Supertrend 10/3 1h con tamaño adaptable — backtest 2 años", "",
             f"Capital inicial ${START:,.0f}. Riesgo total {RiskConfig().total_risk_pct} % repartido entre N posiciones; "
             f"N por capital: {RiskConfig().tiers}. Costo ${COST}/oz.", ""]
    for sym in ("GC=F", "PAXG-USD"):
        df = load(sym, cache)
        months = (df.index[-1] - df.index[0]).days / 30.4
        lines += [f"## {sym} ({len(df):,} velas 1h, {df.index[0]:%d/%m/%Y} → {df.index[-1]:%d/%m/%Y})", "",
                  "| Variante | Capital final | Retorno | Caida max | Operaciones | Acierto | PF | Peor mes | Meses positivos | Sharpe | P(perder un mes) MC |",
                  "|---|---|---|---|---|---|---|---|---|---|---|"]
        for v in variants:
            r = simulate(df, v)
            p_loss = mc_month_loss(r["trades_arr"], r["trades"] / months) if r["trades"] else np.nan
            lines.append(
                f"| {v.name} | ${r['final']:,.0f} | {r['ret'] * 100:+.0f} % | {r['max_dd'] * 100:.0f} % | {r['trades']} | "
                f"{r['win'] * 100:.0f} % | {r['pf']:.2f} | {r['worst_month'] * 100:+.1f} % | {r['pos_months'] * 100:.0f} % | "
                f"{r['sharpe']:.2f} | {p_loss * 100:.0f} % |")
        lines.append("")
    text = "\n".join(lines)
    (Path(__file__).resolve().parent / "resultados.md").write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
