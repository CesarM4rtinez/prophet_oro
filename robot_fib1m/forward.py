"""Informe de la prueba en simulacion (forward test) de la estrategia Fibonacci 1m.

Corre la estrategia sobre TODAS las velas 1m de Capital.com acumuladas (bid/ask reales)
y escribe `<data>/informe.md`: operaciones, acierto, resultado por onza, efecto del
filtro de spread, cuenta de $10 con distintos riesgos y comparacion con el backtest.
No envia ninguna orden.

Uso: python robot_fib1m/forward.py --data <carpeta> [--summary <archivo>]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from collect import load_all  # noqa: E402
from strategy import STOP_USD, equity, simulate, tradable_mask  # noqa: E402

SV = "America/El_Salvador"
BACKTEST = {"ops_dia": 3.5, "acierto": 0.31, "R": 0.5}  # research/manual_style (GC=F, 25 dias)
MIN_TRADES = 100


def stats(t: pd.DataFrame) -> dict:
    t = t[(~t["skipped"]) & (t["reason"] != "abierta")] if not t.empty else t
    if t.empty:
        return {"n": 0}
    r = t["pnl"].to_numpy()
    boot = np.random.default_rng(19).choice(r, size=(3000, len(r))).mean(1)
    return {"n": len(r), "win": (r > 0).mean(), "exp": r.mean(), "R": r.mean() / STOP_USD,
            "lo": np.percentile(boot, 2.5), "hi": np.percentile(boot, 97.5),
            "pf": r[r > 0].sum() / -r[r <= 0].sum() if (r <= 0).any() else float("inf"), "total": r.sum()}


def report(df: pd.DataFrame) -> str:
    if df.empty:
        return "### Prueba en simulacion — Fibonacci 1m\nTodavia no hay velas guardadas.\n"
    ok = tradable_mask(df.index)
    spread = (df["close_ask"] - df["close_bid"])[ok]
    days = df.index[ok].tz_convert(SV).normalize().nunique()
    gaps = (df.index.to_series().diff() > pd.Timedelta(hours=3)) & ok
    L = ["### Prueba en simulacion — Fibonacci 1m con confirmacion (sin ordenes)", "",
         f"- Datos de Capital.com: {len(df):,} velas 1m, {df.index[0].tz_convert(SV):%d/%m %H:%M} → "
         f"{df.index[-1].tz_convert(SV):%d/%m %H:%M} (hora El Salvador), {days} dias de mercado"
         f"{f', {int(gaps.sum())} huecos de datos' if gaps.any() else ''}.",
         f"- Spread real: mediana ${spread.median():.2f}, percentil 90 ${spread.quantile(0.9):.2f}, "
         f"{(spread > 0.5).mean() * 100:.0f} % del tiempo mayor a $0,50.", ""]
    L += ["| Variante | Ops | Ops/dia | Acierto | $/oz por op (IC 95 %) | En R | PF | $10 al 5 % (1:200) | $10 al 5 % (1:20) |",
          "|---|---|---|---|---|---|---|---|---|"]
    for name, ms in (("Sin filtro de spread", None), ("Solo si spread ≤ $0,50", 0.50)):
        tr = simulate(df, max_spread=ms)
        st = stats(tr)
        if st["n"] == 0:
            L.append(f"| {name} | 0 | — | — | — | — | — | — | — |")
            continue
        e200, d200 = equity(tr, 0.05, 200)
        e20, _ = equity(tr, 0.05, 20)
        L.append(f"| {name} | {st['n']} | {st['n'] / max(days, 1):.1f} | {st['win'] * 100:.0f} % | {st['exp']:+.2f} "
                 f"({st['lo']:+.2f} a {st['hi']:+.2f}) | {st['R']:+.2f}R | {st['pf']:.2f} | ${e200:,.2f} (caida {d200 * 100:.0f} %) | ${e20:,.2f} |")
    tr = simulate(df, max_spread=0.50)
    st = stats(tr)
    L.append("")
    if st["n"] < MIN_TRADES:
        L.append(f"**Veredicto:** faltan datos ({st['n']} de {MIN_TRADES} operaciones). Backtest de referencia: "
                 f"~{BACKTEST['ops_dia']} ops/dia, acierto ~{BACKTEST['acierto'] * 100:.0f} %, ~+{BACKTEST['R']}R por operacion.")
    elif st["lo"] > 0:
        L.append(f"**Veredicto:** CONFIRMADA en simulacion ({st['n']} ops, {st['R']:+.2f}R, IC sobre 0). Lista para la subcuenta demo CFDs.")
    elif st["exp"] > 0:
        L.append(f"**Veredicto:** positiva pero no concluyente ({st['n']} ops, {st['R']:+.2f}R, el IC toca 0). Seguir midiendo.")
    else:
        L.append(f"**Veredicto:** NO confirmada ({st['n']} ops, {st['R']:+.2f}R). No automatizar.")
    done = tr[(~tr["skipped"]) & (tr["reason"] != "abierta")].tail(8) if not tr.empty else tr
    if not done.empty:
        L += ["", "Ultimas operaciones simuladas (hora El Salvador):", "",
              "| Entrada | Lado | Precio | Salida | Motivo | $/oz | Spread |", "|---|---|---|---|---|---|---|"]
        for t in done.iloc[::-1].itertuples():
            L.append(f"| {t.time.tz_convert(SV):%d/%m %H:%M} | {'COMPRA' if t.side == 1 else 'VENTA'} | {t.entry:,.2f} | "
                     f"{t.exit:,.2f} | {t.reason} | {t.pnl:+.2f} | {t.spread:.2f} |")
    return "\n".join(L) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    ap.add_argument("--summary")
    a = ap.parse_args()
    text = report(load_all(Path(a.data)))
    (Path(a.data) / "informe.md").write_text(text, encoding="utf-8")
    if a.summary:
        with open(a.summary, "a", encoding="utf-8") as fh:
            fh.write(text)
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
