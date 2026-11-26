"""Pruebas sin red: API de Capital.com y calendario economico simulados."""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import bot  # noqa: E402
import news  # noqa: E402
import risk  # noqa: E402

START = pd.Timestamp("2026-11-16 00:00", tz="UTC")  # lunes
NO_NEWS = ([], "test")


def _prices_body(closes):
    t = pd.date_range(START, periods=len(closes), freq="h")
    prices, prev = [], closes[0]
    for ts, c in zip(t, closes):
        o, h, l = prev, max(prev, c) + 0.5, min(prev, c) - 0.5
        q = lambda v: {"bid": v, "ask": v + 0.3}
        prices.append({"snapshotTimeUTC": ts.strftime("%Y-%m-%dT%H:%M:%S"),
                       "openPrice": q(o), "highPrice": q(h), "lowPrice": q(l), "closePrice": q(c)})
        prev = c
    return {"prices": prices}


def now_after(closes, minutes=5):
    return (START + pd.Timedelta(hours=len(closes)) + pd.Timedelta(minutes=minutes)).to_pydatetime()


def _settings(**kw):
    base = dict(environment="DEMO", api_key="k", identifier="i", password="p", account_name=None, epic="GOLD",
                size=0.1, resolution="HOUR", period=10, factor=3.0, max_signal_age=2, emergency_stop_atr=1.0,
                dry_run=False, enabled=True, allow_live=False, sizing="risk", state_file=None)
    base.update(kw)
    return bot.Settings(**base)


def _cfg(**kw):
    c = risk.RiskConfig(total_risk_pct=1.5)
    for k, v in kw.items():
        setattr(c, k, v)
    return c


def _cut_at_flip(closes, kind):
    """Recorta la serie para que el cambio de color caiga en la ULTIMA vela cerrada."""
    st = bot.supertrend(bot.parse_prices(_prices_body(closes)), 10, 3.0)
    idx = int(np.flatnonzero(st[kind].to_numpy())[-1])
    return list(closes[: idx + 1])


# Sube y luego cae fuerte: el Supertrend acaba de pasar a ROJO en la ultima vela.
FRESH_RED = _cut_at_flip(list(np.linspace(3000, 3300, 120)) + list(np.linspace(3300, 3100, 20)), "sell")
# Rojo desde hace muchas velas (señal vieja).
OLD_RED = FRESH_RED + list(np.linspace(FRESH_RED[-1], FRESH_RED[-1] - 100, 30))
# Baja y luego sube: acaba de pasar a VERDE en la ultima vela.
FRESH_GREEN = _cut_at_flip(list(np.linspace(3300, 3000, 120)) + list(np.linspace(3000, 3200, 20)), "buy")


class FakeResp:
    def __init__(self, body, headers=None, status=200):
        self._b, self.headers, self.status_code, self.text = body, headers or {}, status, ""

    @property
    def ok(self):
        return self.status_code < 400

    def json(self):
        return self._b


class FakeCapital:
    def __init__(self, closes, positions, balance=10_000.0, dm_balance=1_000.0):
        self.body = _prices_body(closes)
        self.last = closes[-1]
        self.positions = positions
        self.balance, self.dm_balance = balance, dm_balance
        self.calls = []

    def __call__(self, method, url, headers=None, timeout=None, json=None, params=None):
        path = url.split(".com", 1)[1]
        self.calls.append((method, path, json))
        if path == "/api/v1/session" and method == "POST":
            return FakeResp({"currentAccountId": "A1"}, {"CST": "c", "X-SECURITY-TOKEN": "t"})
        if path == "/api/v1/session" and method == "PUT":
            return FakeResp({}, {"CST": "c2", "X-SECURITY-TOKEN": "t2"})
        if path == "/api/v1/accounts":
            return FakeResp({"accounts": [
                {"accountId": "A1", "accountName": "Principal", "currency": "USD",
                 "balance": {"balance": self.balance, "profitLoss": 0, "available": self.balance}},
                {"accountId": "A2", "accountName": "dm", "currency": "USD",
                 "balance": {"balance": self.dm_balance, "profitLoss": 0, "available": self.dm_balance}}]})
        if path.startswith("/api/v1/markets/"):
            return FakeResp({"dealingRules": {"minDealSize": {"value": 0.01}, "minSizeIncrement": {"value": 0.01}},
                             "snapshot": {"bid": self.last, "offer": self.last + 0.3}})
        if path.startswith("/api/v1/prices/"):
            return FakeResp(self.body)
        if path == "/api/v1/positions" and method == "GET":
            return FakeResp({"positions": [{"position": p, "market": {"epic": "GOLD"}} for p in self.positions]})
        if path.startswith("/api/v1/positions") and method in ("POST", "DELETE", "PUT"):
            return FakeResp({"dealReference": "ref1"})
        if path.startswith("/api/v1/confirms/"):
            return FakeResp({"dealStatus": "ACCEPTED", "level": self.last, "affectedDeals": [{"dealId": "NEW1"}]})
        return FakeResp({})


def _run(monkeypatch, closes, positions, settings=None, cfg=None, calendar=NO_NEWS, now=None, **fake_kw):
    fake = FakeCapital(closes, positions, **fake_kw)
    monkeypatch.setattr(bot.requests, "request", fake)
    d = bot.run(settings or _settings(), now=now or now_after(closes), calendar=calendar,
                cfg=cfg or _cfg(), news_cfg=news.NewsConfig())
    return d, fake


def _opened(fake):
    return [j for m, p, j in fake.calls if m == "POST" and p == "/api/v1/positions"]


def _closed(fake):
    return [p for m, p, _ in fake.calls if m == "DELETE" and p.startswith("/api/v1/positions/")]


# ----------------------------------------------------------------- señal y vuelta

def test_closed_bars_drops_forming_candle():
    df = bot.parse_prices(_prices_body(FRESH_RED))
    now = (df.index[-1] + pd.Timedelta(minutes=30)).to_pydatetime()
    assert bot.closed_bars(df, "HOUR", now).index[-1] == df.index[-2]


def test_flip_closes_long_and_opens_risk_sized_short(monkeypatch):
    d, fake = _run(monkeypatch, FRESH_RED, [{"dealId": "L1", "direction": "BUY", "size": 0.3, "level": 3200,
                                              "stopLevel": 3100, "createdDateUTC": "2026-11-20T00:00:00"}])
    assert d["color"] == "ROJO" and "/api/v1/positions/L1" in _closed(fake)
    o = _opened(fake)[0]
    assert o["direction"] == "SELL" and o["stopLevel"] > d["price"]
    # capital 10 000, riesgo 1,5 % repartido en N=3 -> $50 por posicion
    assert d["n_max"] == 3
    loss_at_stop = (o["stopLevel"] - d["price"] + 0.30) * o["size"]
    assert 40 <= loss_at_stop <= 50.01


def test_green_flip_closes_short_and_buys(monkeypatch):
    d, fake = _run(monkeypatch, FRESH_GREEN, [{"dealId": "S1", "direction": "SELL", "size": 0.1, "level": 3100,
                                                "stopLevel": 3200, "createdDateUTC": "2026-11-20T00:00:00"}])
    assert "/api/v1/positions/S1" in _closed(fake)
    assert _opened(fake)[0]["direction"] == "BUY" and _opened(fake)[0]["stopLevel"] < d["price"]


def test_stale_signal_without_position_waits(monkeypatch):
    d, fake = _run(monkeypatch, OLD_RED, [])
    assert d["decision"].startswith("ESPERAR") and not _opened(fake)


def test_dry_run_sends_no_orders(monkeypatch):
    d, fake = _run(monkeypatch, FRESH_RED, [{"dealId": "L1", "direction": "BUY", "size": 0.1, "level": 3200,
                                              "stopLevel": 3100}], settings=_settings(dry_run=True))
    assert d["actions"] and not _opened(fake) and not _closed(fake)


# ----------------------------------------------------------------- escalado

def test_size_scales_with_capital_and_risk_is_split_by_n():
    cfg = _cfg()
    s1, _ = risk.position_size(10_000, 3500, 3480, n_max=1, open_size=0, cfg=cfg)
    s2, _ = risk.position_size(20_000, 3500, 3480, n_max=1, open_size=0, cfg=cfg)
    s3, _ = risk.position_size(20_000, 3500, 3480, n_max=2, open_size=0, cfg=cfg)
    assert s2 == pytest.approx(2 * s1, abs=0.011)          # el doble de capital, el doble de tamaño
    assert s3 == pytest.approx(s1, abs=0.011)              # N=2 reparte el riesgo
    assert [risk.max_units_for_equity(e, cfg) for e in (500, 5_000, 20_000, 80_000)] == [1, 2, 3, 4]


def test_stop_too_far_refuses_instead_of_shrinking():
    size, why = risk.position_size(100, 3500, 3300, n_max=1, open_size=0, cfg=_cfg())
    assert size == 0 and "minimo" in why


def test_pyramid_adds_when_trend_advances(monkeypatch):
    up = list(np.linspace(3300, 3000, 120)) + list(np.linspace(3000, 3200, 12))
    pos = [{"dealId": "B1", "direction": "BUY", "size": 0.2, "level": 3100, "stopLevel": 3120,
            "createdDateUTC": "2026-11-20T00:00:00"}]  # stop ya asegura ganancia -> riesgo abierto 0
    d, fake = _run(monkeypatch, up, pos)
    assert d["decision"].startswith("AGREGAR") and _opened(fake)[0]["direction"] == "BUY"


def test_pyramid_respects_n_max_and_one_add_per_bar(monkeypatch):
    up = list(np.linspace(3300, 3000, 120)) + list(np.linspace(3000, 3200, 12))
    last_bar_end = (START + pd.Timedelta(hours=len(up))).strftime("%Y-%m-%dT%H:%M:%S")
    pos = [{"dealId": "B1", "direction": "BUY", "size": 0.2, "level": 3100, "stopLevel": 3120,
            "createdDateUTC": last_bar_end}]  # ya se agrego en la vela actual
    d, fake = _run(monkeypatch, up, pos)
    assert not _opened(fake) and "vela" in d["decision"]
    pos3 = [dict(pos[0], dealId=f"B{i}", createdDateUTC="2026-11-20T00:00:00") for i in range(3)]
    d, fake = _run(monkeypatch, up, pos3)  # N max = 3 con $10 000
    assert not _opened(fake) and "N max" in d["decision"]


def test_small_account_uses_one_position(monkeypatch):
    d, fake = _run(monkeypatch, FRESH_RED, [], settings=_settings(account_name="dm"))
    assert ("PUT", "/api/v1/session", {"accountId": "A2"}) in fake.calls
    assert d["capital"]["equity"] == 1_000 and d["n_max"] == 1 and d["cuenta"].startswith("dm")


# ----------------------------------------------------------------- noticias

def _event(when, title="Core PCE Price Index m/m", impact="High", country="USD"):
    return {"title": title, "country": country, "impact": impact,
            "date": pd.Timestamp(when).tz_convert("America/New_York").isoformat()}


def test_news_blocks_new_entry_but_not_exits(monkeypatch):
    now = now_after(FRESH_RED)
    cal = (news.parse_calendar([_event(pd.Timestamp(now) + pd.Timedelta(minutes=10))]), "test")
    d, fake = _run(monkeypatch, FRESH_RED, [{"dealId": "L1", "direction": "BUY", "size": 0.1, "level": 3200,
                                              "stopLevel": 3100}], calendar=cal)
    assert "/api/v1/positions/L1" in _closed(fake)  # salir nunca se bloquea
    assert not _opened(fake) and "noticias" in d["decision"] and "PCE" in d["decision"]


def test_news_outside_window_allows_entry(monkeypatch):
    now = now_after(FRESH_RED)
    cal = (news.parse_calendar([_event(pd.Timestamp(now) + pd.Timedelta(hours=5)),
                                _event(pd.Timestamp(now), title="German Ifo", country="EUR")]), "test")
    d, fake = _run(monkeypatch, FRESH_RED, [], calendar=cal)
    assert _opened(fake) and "PCE" in bot._summary(d)


def test_us_holiday_blocks_entries(monkeypatch):
    now = now_after(FRESH_RED)
    noon_ny = pd.Timestamp(now).tz_convert("America/New_York").normalize() + pd.Timedelta(hours=12)
    cal = (news.parse_calendar([_event(noon_ny, title="Bank Holiday", impact="Holiday")]), "test")
    d, fake = _run(monkeypatch, FRESH_RED, [], calendar=cal)
    assert not _opened(fake) and "feriado" in d["decision"]


def test_calendar_failure_blocks_usual_release_windows():
    cfg = news.NewsConfig()
    at_830 = pd.Timestamp("2026-11-25 08:35", tz="America/New_York")
    at_1130 = pd.Timestamp("2026-11-25 11:30", tz="America/New_York")
    assert news.check_news(at_830, [], "fallo", cfg)["block"] is True
    assert news.check_news(at_1130, [], "fallo", cfg)["block"] is False


# ----------------------------------------------------------------- frenos y seguridad

def test_daily_loss_breaker_blocks_entries(monkeypatch, tmp_path):
    state = tmp_path / "state.json"
    day = pd.Timestamp(now_after(FRESH_RED)).tz_convert("America/New_York").strftime("%Y-%m-%d")
    state.write_text(json.dumps({"day": day, "day_start_equity": 10_500, "peak_equity": 10_500}))
    d, fake = _run(monkeypatch, FRESH_RED, [], settings=_settings(state_file=str(state)))
    assert not _opened(fake) and "perdida diaria" in d["decision"]


def test_drawdown_breaker_halts_until_manual_reset(monkeypatch, tmp_path):
    state = tmp_path / "state.json"
    state.write_text(json.dumps({"peak_equity": 20_000}))
    d, fake = _run(monkeypatch, FRESH_RED, [], settings=_settings(state_file=str(state)))
    assert not _opened(fake) and json.loads(state.read_text()).get("halted")


def test_disabled_and_live_guards():
    assert bot.run(_settings(enabled=False))["status"] == "deshabilitado"
    with pytest.raises(RuntimeError, match="BOT_ALLOW_LIVE"):
        bot.run(_settings(environment="LIVE"))


def test_matches_dashboard_supertrend():
    from core import supertrend as dash
    assert bot.supertrend is dash.supertrend
