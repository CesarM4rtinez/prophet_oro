"""Pruebas sin red: API de Capital.com simulada (no se envia nada real)."""
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import bot  # noqa: E402


def _prices_body(closes, start="2026-11-20 00:00"):
    t = pd.date_range(start, periods=len(closes), freq="h", tz="UTC")
    prices = []
    prev = closes[0]
    for ts, c in zip(t, closes):
        o, h, l = prev, max(prev, c) + 0.5, min(prev, c) - 0.5
        q = lambda v: {"bid": v, "ask": v + 0.3}
        prices.append({"snapshotTimeUTC": ts.strftime("%Y-%m-%dT%H:%M:%S"),
                       "openPrice": q(o), "highPrice": q(h), "lowPrice": q(l), "closePrice": q(c)})
        prev = c
    return {"prices": prices}


def _settings(**kw):
    base = dict(environment="DEMO", api_key="k", identifier="i", password="p", account_name=None, epic="GOLD",
                size=0.1, resolution="HOUR", period=10, factor=3.0, max_signal_age=0, emergency_stop_atr=1.0,
                dry_run=False, enabled=True, allow_live=False)
    base.update(kw)
    return bot.Settings(**base)


# Serie: sube 120 velas, luego cae fuerte -> el Supertrend pasa a ROJO al final.
UP_THEN_DOWN = list(np.linspace(3000, 3300, 120)) + list(np.linspace(3300, 3150, 8))


class FakeResp:
    def __init__(self, body, headers=None, status=200):
        self._b, self.headers, self.status_code, self.text = body, headers or {}, status, ""

    @property
    def ok(self):
        return self.status_code < 400

    def json(self):
        return self._b


class FakeCapital:
    def __init__(self, closes, positions):
        self.body = _prices_body(closes)
        self.positions = positions
        self.calls = []

    def __call__(self, method, url, headers=None, timeout=None, json=None, params=None):
        path = url.split(".com", 1)[1]
        self.calls.append((method, path, json))
        if path == "/api/v1/session" and method == "POST":
            return FakeResp({"currentAccountId": "A1"}, {"CST": "c", "X-SECURITY-TOKEN": "t"})
        if path.startswith("/api/v1/prices/"):
            return FakeResp(self.body)
        if path == "/api/v1/positions" and method == "GET":
            return FakeResp({"positions": [{"position": p, "market": {"epic": "GOLD"}} for p in self.positions]})
        if path.startswith("/api/v1/positions") and method in ("POST", "DELETE"):
            return FakeResp({"dealReference": "ref1"})
        if path.startswith("/api/v1/confirms/"):
            return FakeResp({"dealStatus": "ACCEPTED", "level": 3150.0})
        return FakeResp({})


NOW = datetime(2026, 11, 25, 8, 5, tzinfo=timezone.utc)  # despues del cierre de la ultima vela


def test_closed_bars_drops_forming_candle():
    df = bot.parse_prices(_prices_body(UP_THEN_DOWN))
    last_start = df.index[-1]
    now = (last_start + pd.Timedelta(minutes=30)).to_pydatetime()
    assert bot.closed_bars(df, "HOUR", now).index[-1] == df.index[-2]


def test_flip_closes_long_and_opens_short(monkeypatch):
    fake = FakeCapital(UP_THEN_DOWN, [{"dealId": "L1", "direction": "BUY", "size": 0.1, "level": 3200}])
    monkeypatch.setattr(bot.requests, "request", fake)
    d = bot.run(_settings(), now=NOW)
    assert d["color"] == "ROJO" and d["action"] == "DAR_VUELTA"
    methods = [(m, p) for m, p, _ in fake.calls]
    assert ("DELETE", "/api/v1/positions/L1") in methods
    opened = [j for m, p, j in fake.calls if m == "POST" and p == "/api/v1/positions"]
    assert opened and opened[0]["direction"] == "SELL" and opened[0]["size"] == 0.1
    assert opened[0]["stopLevel"] > d["close"]  # stop de emergencia por encima en una venta


def test_same_direction_does_not_trade(monkeypatch):
    fake = FakeCapital(UP_THEN_DOWN, [{"dealId": "S1", "direction": "SELL", "size": 0.1, "level": 3250}])
    monkeypatch.setattr(bot.requests, "request", fake)
    d = bot.run(_settings(), now=NOW)
    assert d["action"] == "MANTENER"
    assert not [1 for m, p, _ in fake.calls if m == "POST" and p == "/api/v1/positions"]


def test_dry_run_sends_no_orders(monkeypatch):
    fake = FakeCapital(UP_THEN_DOWN, [{"dealId": "L1", "direction": "BUY", "size": 0.1, "level": 3200}])
    monkeypatch.setattr(bot.requests, "request", fake)
    d = bot.run(_settings(dry_run=True), now=NOW)
    assert d["action"] == "DAR_VUELTA"
    assert not [1 for m, p, _ in fake.calls if m in ("POST", "DELETE") and p.startswith("/api/v1/positions")]


OLD_RED = UP_THEN_DOWN + list(np.linspace(3150, 3050, 30))  # rojo desde hace muchas velas
LATER = NOW + pd.Timedelta(hours=40)


def _opened(fake):
    return [j for m, p, j in fake.calls if m == "POST" and p == "/api/v1/positions"]


def test_red_without_position_sells_now_by_default(monkeypatch):
    fake = FakeCapital(OLD_RED, [])
    monkeypatch.setattr(bot.requests, "request", fake)
    d = bot.run(_settings(), now=LATER)
    assert d["color"] == "ROJO" and d["action"] == "ABRIR"
    assert _opened(fake)[0]["direction"] == "SELL"
    assert _opened(fake)[0]["stopLevel"] > d["close"]


def test_green_without_position_buys_now_by_default(monkeypatch):
    closes = list(np.linspace(3300, 3000, 120)) + list(np.linspace(3000, 3150, 40))
    fake = FakeCapital(closes, [])
    monkeypatch.setattr(bot.requests, "request", fake)
    d = bot.run(_settings(), now=LATER)
    assert d["color"] == "VERDE" and _opened(fake)[0]["direction"] == "BUY"
    assert _opened(fake)[0]["stopLevel"] < d["close"]


def test_green_flip_closes_short_and_buys(monkeypatch):
    closes = list(np.linspace(3300, 3000, 120)) + list(np.linspace(3000, 3150, 8))
    fake = FakeCapital(closes, [{"dealId": "S1", "direction": "SELL", "size": 0.1, "level": 3100}])
    monkeypatch.setattr(bot.requests, "request", fake)
    d = bot.run(_settings(), now=NOW)
    assert d["color"] == "VERDE" and d["action"] == "DAR_VUELTA"
    assert ("DELETE", "/api/v1/positions/S1") in [(m, p) for m, p, _ in fake.calls]
    assert _opened(fake)[0]["direction"] == "BUY"


def test_stale_signal_waits_when_age_limit_set(monkeypatch):
    fake = FakeCapital(OLD_RED, [])
    monkeypatch.setattr(bot.requests, "request", fake)
    d = bot.run(_settings(max_signal_age=3), now=LATER)
    assert d["action"] == "ESPERAR" and not _opened(fake)


def test_disabled_and_live_guards(monkeypatch):
    assert bot.run(_settings(enabled=False))["status"] == "deshabilitado"
    with pytest.raises(RuntimeError, match="BOT_ALLOW_LIVE"):
        bot.run(_settings(environment="LIVE"))


def test_matches_dashboard_supertrend():
    """El robot y el dashboard usan exactamente la misma funcion."""
    from core import supertrend as dash
    assert bot.supertrend is dash.supertrend
