"""Descarga velas de 1 minuto de Capital.com (bid y ask) y las acumula por dia.

Cada ejecucion pide las ultimas 1 000 velas de 1 minuto (~16 horas), descarta la vela en
formacion y las fusiona con lo ya guardado en `<data>/GOLD_1m_AAAA-MM-DD.csv`. Si GitHub
se atrasa unas horas no se pierden datos; si se atrasa mas de ~16 horas queda un hueco
(el informe lo muestra).

Uso: python robot_fib1m/collect.py --data <carpeta>
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "robot_supertrend"))
import bot  # noqa: E402  (mismo cliente de Capital.com que el robot)

COLS = [f"{c}_{s}" for c in ("open", "high", "low", "close") for s in ("bid", "ask")]


def parse_bid_ask(body: dict) -> pd.DataFrame:
    rows = []
    for p in body.get("prices", []):
        row = {"time": p.get("snapshotTimeUTC") or p.get("snapshotTime")}
        for c, key in (("open", "openPrice"), ("high", "highPrice"), ("low", "lowPrice"), ("close", "closePrice")):
            q = p.get(key) or {}
            row[f"{c}_bid"], row[f"{c}_ask"] = q.get("bid"), q.get("ask")
        rows.append(row)
    df = pd.DataFrame(rows).dropna()
    if df.empty:
        return pd.DataFrame(columns=COLS)
    df["time"] = pd.to_datetime(df["time"], utc=True)
    return df.set_index("time")[COLS].astype(float).sort_index()


def merge_into(data: Path, new: pd.DataFrame, epic: str) -> int:
    """Fusiona por dia (UTC). Devuelve cuantas velas nuevas se agregaron."""
    data.mkdir(parents=True, exist_ok=True)
    added = 0
    for day, chunk in new.groupby(new.index.date):
        path = data / f"{epic}_1m_{day}.csv"
        old = load_day(path)
        both = pd.concat([old, chunk])
        both = both[~both.index.duplicated(keep="last")].sort_index()
        added += len(both) - len(old)
        both.to_csv(path, index_label="time", float_format="%.3f")
    return added


def load_day(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame(columns=COLS)
    df = pd.read_csv(path, index_col="time")
    df.index = pd.to_datetime(df.index, utc=True)
    return df


def load_all(data: Path, epic: str = "GOLD") -> pd.DataFrame:
    files = sorted(data.glob(f"{epic}_1m_*.csv"))
    if not files:
        return pd.DataFrame(columns=COLS)
    df = pd.concat([load_day(f) for f in files])
    return df[~df.index.duplicated(keep="last")].sort_index()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True)
    a = ap.parse_args()
    s = bot.Settings.from_env()
    s.account_name = None  # los precios no dependen de la subcuenta
    if not (s.api_key and s.identifier and s.password):
        print("ERROR: faltan CAPITAL_API_KEY / CAPITAL_IDENTIFIER / CAPITAL_PASSWORD")
        return 1
    api = bot.CapitalAPI(s)
    api.login()
    try:
        body = api._req("GET", f"/api/v1/prices/{s.epic}", params={"resolution": "MINUTE", "max": 1000}).json()
    finally:
        api.logout()
    df = parse_bid_ask(body)
    now = pd.Timestamp(datetime.now(timezone.utc))
    df = df[df.index + pd.Timedelta(minutes=1) <= now]  # sin la vela en formacion
    added = merge_into(Path(a.data), df, s.epic)
    print(f"Velas recibidas: {len(df)} ({df.index.min()} -> {df.index.max()}) · nuevas guardadas: {added}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
