"""Pruebas sin red de la estrategia Fibonacci 1m y del recolector de datos."""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import collect  # noqa: E402
import forward  # noqa: E402
import strategy as S  # noqa: E402

T0 = pd.Timestamp("2026-11-17 14:00", tz="UTC")  # martes 09:00 NY, mercado abierto


def _frame(mid_rows, spread=0.30, spreads=None):
    """mid_rows: lista de (open, high, low, close) del precio medio."""
    idx = pd.date_range(T0, periods=len(mid_rows), freq="min")
    m = pd.DataFrame(mid_rows, columns=["open", "high", "low", "close"], index=idx)
    sp = pd.Series(spread, index=idx) if spreads is None else pd.Series(spreads, index=idx)
    out = {}
    for c in ("open", "high", "low", "close"):
        out[f"{c}_bid"] = m[c] - sp / 2
        out[f"{c}_ask"] = m[c] + sp / 2
    return pd.DataFrame(out, index=idx)


def _scenario(after_entry):
    """Impulso alcista 3000 -> 3020 confirmado en la vela 50, retroceso a 0,618 (3007,64),
    cierre de vuelta sobre 0,5 (3010) en la vela 52 -> entrada en la apertura de la 53."""
    rows = [(3000 + k * 20 / 49,) * 4 for k in range(50)]
    rows += [(3016, 3016.5, 3012, 3012),     # 50: confirma el giro (impulso parcheado)
             (3012, 3012.5, 3007.0, 3009),   # 51: toca 0,618
             (3009, 3011.5, 3008.5, 3011),   # 52: cierra sobre 0,5 -> confirmacion
             (3011, 3011.5, 3010.5, 3011)]   # 53: entrada a la apertura (ask 3011,15)
    rows += after_entry
    rows += [(rows[-1][3],) * 4 for _ in range(20)]
    return rows


@pytest.fixture(autouse=True)
def _patch(monkeypatch):
    monkeypatch.setattr(S, "impulses", lambda h, l, atr: [(50, 3000.0, 3020.0, 1)])
    monkeypatch.setattr(S, "htf_trend", lambda mid, minutes, **k: np.ones(len(mid)))


def test_long_hits_target_with_real_spread():
    up = [(3011 + k, 3012 + k, 3010.5 + k, 3012 + k) for k in range(16)]  # sube hasta tocar 3025,44
    tr = S.simulate(_frame(_scenario(up)))
    t = tr[~tr.skipped].iloc[0]
    assert t.side == 1 and t.reason == "objetivo"
    assert t.entry == pytest.approx(3011.15)                      # compra al ASK
    assert t.target == pytest.approx(3020 + 0.272 * 20)
    assert t.pnl == pytest.approx(t.target - 3011.15)


def test_long_stopped_on_bid_loses_exactly_the_stop():
    down = [(3010, 3010.5, 3007.0, 3008), (3008, 3008.5, 3005, 3006)]
    tr = S.simulate(_frame(_scenario(down)))
    t = tr[~tr.skipped].iloc[0]
    assert t.reason == "stop" and t.pnl == pytest.approx(-S.STOP_USD)


def test_wide_spread_skips_entry_only_with_filter():
    rows = _scenario([(3011 + k, 3012 + k, 3010.5 + k, 3012 + k) for k in range(16)])
    spreads = [0.30] * len(rows)
    spreads[52] = 1.80  # spread nocturno como en la captura del usuario
    tr = S.simulate(_frame(rows, spreads=spreads), max_spread=0.50)
    assert tr.iloc[0].skipped and not (~tr.skipped).any()
    tr2 = S.simulate(_frame(rows, spreads=spreads))
    assert (~tr2.skipped).sum() == 1


def test_no_trade_against_higher_timeframes(monkeypatch):
    monkeypatch.setattr(S, "htf_trend", lambda mid, minutes, **k: -np.ones(len(mid)))
    tr = S.simulate(_frame(_scenario([(3011,) * 4])))
    assert tr.empty


def test_equity_respects_leverage_cap():
    trades = pd.DataFrame([{"entry": 3500.0, "pnl": 10.0, "reason": "objetivo", "skipped": False}] * 3)
    e20, _ = S.equity(trades, risk_pct=0.5, leverage=20)     # a 1:20 el margen topa el tamaño
    e200, _ = S.equity(trades, risk_pct=0.5, leverage=200)
    assert e200 > e20 > 10


def test_parse_and_merge_by_day(tmp_path):
    body = {"prices": [
        {"snapshotTimeUTC": "2026-11-25T23:58:00", "openPrice": {"bid": 1, "ask": 1.3}, "highPrice": {"bid": 2, "ask": 2.3},
         "lowPrice": {"bid": 0.5, "ask": 0.8}, "closePrice": {"bid": 1.5, "ask": 1.8}},
        {"snapshotTimeUTC": "2026-11-26T00:01:00", "openPrice": {"bid": 1, "ask": 1.3}, "highPrice": {"bid": 2, "ask": 2.3},
         "lowPrice": {"bid": 0.5, "ask": 0.8}, "closePrice": {"bid": 1.5, "ask": 1.8}}]}
    df = collect.parse_bid_ask(body)
    assert list(df.columns) == collect.COLS and len(df) == 2
    assert collect.merge_into(tmp_path, df, "GOLD") == 2
    assert collect.merge_into(tmp_path, df, "GOLD") == 0          # repetir no duplica
    assert sorted(p.name for p in tmp_path.glob("*.csv")) == ["GOLD_1m_2026-11-25.csv", "GOLD_1m_2026-11-26.csv"]
    assert len(collect.load_all(tmp_path)) == 2


def test_report_without_data_and_with_few_trades(tmp_path):
    assert "no hay velas" in forward.report(pd.DataFrame())
    rows = _scenario([(3011 + k, 3012 + k, 3010.5 + k, 3012 + k) for k in range(16)])
    text = forward.report(_frame(rows))
    assert "faltan datos" in text and "COMPRA" in text
