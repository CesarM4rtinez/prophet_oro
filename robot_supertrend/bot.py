"""Robot Supertrend 10/3 (1h) para el CFD GOLD de Capital.com — v2.

Señal (sin cambios, la del usuario, sobre velas 1h CERRADAS):
- Supertrend pasa a VERDE -> COMPRA; pasa a ROJO -> VENTA; al cambiar de color se
  cierran TODAS las posiciones y se abre la direccion nueva.

Novedades v2 (validadas en research/scaling_1h, 2 años de velas 1h):
1. Tamaño adaptable al capital (`risk.py`): el riesgo TOTAL abierto (RISK_TOTAL_PCT,
   1,5 % por defecto) se reparte entre las N posiciones que permite el capital
   (1 si < $2 000, 2 si < $10 000, 3 si < $50 000, 4 desde ahi). Cada posicion arriesga
   capital * riesgo / N hasta su stop. Al crecer la cuenta crecen el tamaño y N.
2. Piramidacion: con la tendencia a favor, agrega una posicion cada vez que el precio
   avanza RISK_ADD_EVERY_ATR ATR desde la ultima entrada (maximo una por vela, hasta N),
   solo si el riesgo abierto no supera el riesgo total.
3. Solo entra en el cambio de color (BOT_MAX_SIGNAL_AGE, por defecto 2 velas), nunca a
   mitad de una tendencia vieja (lo que causo la perdida del 25/11 en $3 505).
4. Stop obligatorio en el broker = linea Supertrend -/+ RISK_STOP_ATR ATR, que solo se
   mueve a favor.
5. Frenos (trader-risk): sin nuevas entradas el resto del dia si el capital cae
   RISK_DAILY_LOSS_PCT % desde el inicio del dia, ni hasta revision manual si cae
   RISK_MAX_DRAWDOWN_PCT % desde su maximo (requiere el archivo de estado del runner).
6. Filtro de noticias (`news.py`): no abre ni agrega posiciones alrededor de eventos
   de alto impacto de EE. UU. ni en feriados; cerrar nunca se bloquea.
7. `runner.py` lo ejecuta de forma continua (cada minuto) en cualquier PC o servidor.

Seguridad: BOT_ENABLED, BOT_DRY_RUN y doble llave para LIVE (CAPITAL_ENV=LIVE +
BOT_ALLOW_LIVE=true). Claves solo por variables de entorno. Gestiona TODAS las posiciones
del instrumento en la subcuenta elegida.
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "oro_dashboard"))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from core.supertrend import rma_atr, supertrend  # noqa: E402  (mismo codigo que el dashboard)
from news import NewsConfig, check_news, fetch_calendar  # noqa: E402
from risk import RiskConfig, max_units_for_equity, open_risk, position_size, round_down  # noqa: E402

BASE_URLS = {
    "DEMO": "https://demo-api-capital.backend-capital.com",
    "LIVE": "https://api-capital.backend-capital.com",
}
RESOLUTION_MINUTES = {"MINUTE_5": 5, "MINUTE_15": 15, "MINUTE_30": 30, "HOUR": 60, "HOUR_4": 240}


def _env(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name, "")
    return value.strip() if value.strip() else default


def _flag(name: str, default: bool = False) -> bool:
    return (_env(name, "true" if default else "false") or "").lower() in ("1", "true", "yes", "si", "sí")


@dataclass
class Settings:
    environment: str
    api_key: str
    identifier: str
    password: str
    account_name: str | None
    epic: str
    size: float
    resolution: str
    period: int
    factor: float
    max_signal_age: int
    emergency_stop_atr: float
    dry_run: bool
    enabled: bool
    allow_live: bool
    sizing: str = "risk"                 # "risk" (adaptable al capital) o "fixed" (BOT_SIZE)
    state_file: str | None = None        # estado para los frenos (lo usa runner.py)

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            environment=(_env("CAPITAL_ENV", "DEMO") or "DEMO").upper(),
            api_key=_env("CAPITAL_API_KEY", "") or "",
            identifier=_env("CAPITAL_IDENTIFIER", "") or "",
            password=_env("CAPITAL_PASSWORD", "") or "",
            account_name=_env("CAPITAL_ACCOUNT_NAME"),
            epic=_env("BOT_EPIC", "GOLD") or "GOLD",
            size=float(_env("BOT_SIZE", "0.1") or 0.1),
            resolution=_env("BOT_RESOLUTION", "HOUR") or "HOUR",
            period=int(_env("ST_PERIOD", "10") or 10),
            factor=float(_env("ST_FACTOR", "3") or 3),
            max_signal_age=int(_env("BOT_MAX_SIGNAL_AGE", "2") or 2),
            emergency_stop_atr=float(_env("BOT_EMERGENCY_STOP_ATR", "1.0") or 1.0),
            dry_run=_flag("BOT_DRY_RUN", False),
            enabled=_flag("BOT_ENABLED", False),
            allow_live=_flag("BOT_ALLOW_LIVE", False),
            sizing=(_env("BOT_SIZING", "risk") or "risk").lower(),
            state_file=_env("BOT_STATE_FILE"),
        )


class CapitalAPI:
    """Cliente REST minimo de Capital.com (mismas llamadas que
    capital_wma_rsi_trader/core/capital_client.py, sin dependencia de Streamlit)."""

    def __init__(self, s: Settings):
        self.s = s
        self.base = BASE_URLS[s.environment]
        self.cst = self.token = None
        self.account_label = "(cuenta por defecto)"
        self.account_id: str | None = None

    def _h(self) -> dict:
        h = {"X-CAP-API-KEY": self.s.api_key, "Content-Type": "application/json"}
        if self.cst:
            h.update({"CST": self.cst, "X-SECURITY-TOKEN": self.token})
        return h

    def _req(self, method: str, path: str, **kw) -> requests.Response:
        r = requests.request(method, self.base + path, headers=self._h(), timeout=20, **kw)
        if not r.ok:
            try:
                detail = r.json().get("errorCode", r.text[:200])
            except ValueError:
                detail = r.text[:200]
            raise RuntimeError(f"Capital.com {method} {path} -> {r.status_code}: {detail}")
        return r

    def login(self) -> None:
        r = self._req("POST", "/api/v1/session",
                      json={"identifier": self.s.identifier, "password": self.s.password, "encryptedPassword": False})
        self.cst, self.token = r.headers.get("CST"), r.headers.get("X-SECURITY-TOKEN")
        if not (self.cst and self.token):
            raise RuntimeError("Capital.com no devolvio tokens de sesion.")
        current = r.json().get("currentAccountId")
        self.account_id = current
        self.account_label = f"(cuenta por defecto, id {current})"
        if self.s.account_name:
            accounts = self._req("GET", "/api/v1/accounts").json().get("accounts", [])
            target = self.s.account_name.strip().lower()
            match = [a for a in accounts if (a.get("accountName") or "").strip().lower() == target]
            if not match:
                names = ", ".join(a.get("accountName", "?") for a in accounts)
                raise RuntimeError(f"No existe la subcuenta '{self.s.account_name}'. Disponibles: {names}")
            if match[0]["accountId"] != current:
                r = self._req("PUT", "/api/v1/session", json={"accountId": match[0]["accountId"]})
                self.cst = r.headers.get("CST") or self.cst
                self.token = r.headers.get("X-SECURITY-TOKEN") or self.token
            self.account_id = match[0]["accountId"]
            self.account_label = f"{match[0].get('accountName')} (id {match[0]['accountId']})"

    def logout(self) -> None:
        try:
            if self.cst:
                self._req("DELETE", "/api/v1/session")
        except RuntimeError:
            pass

    def equity(self) -> dict:
        """Capital de la cuenta activa: balance + resultado abierto."""
        for a in self._req("GET", "/api/v1/accounts").json().get("accounts", []):
            if a.get("accountId") == self.account_id:
                bal = a.get("balance") or {}
                balance = float(bal.get("balance", 0) or 0)
                pl = float(bal.get("profitLoss", 0) or 0)
                return {"balance": balance, "pl": pl, "equity": balance + pl, "currency": a.get("currency", ""),
                        "available": float(bal.get("available", 0) or 0)}
        raise RuntimeError("No se pudo leer el capital de la cuenta activa.")

    def market_rules(self, epic: str) -> dict:
        """Tamaño minimo / paso y precios actuales del instrumento (con valores seguros si faltan)."""
        try:
            body = self._req("GET", f"/api/v1/markets/{epic}").json()
        except RuntimeError:
            body = {}
        rules = body.get("dealingRules") or {}
        snap = body.get("snapshot") or {}

        def val(key, default):
            v = (rules.get(key) or {}).get("value")
            return float(v) if v not in (None, "") else default
        return {"min_size": val("minDealSize", 0.01), "size_step": val("minSizeIncrement", 0.01),
                "bid": snap.get("bid"), "offer": snap.get("offer"), "status": snap.get("marketStatus")}

    def candles(self, epic: str, resolution: str, max_points: int = 400) -> pd.DataFrame:
        body = self._req("GET", f"/api/v1/prices/{epic}", params={"resolution": resolution, "max": max_points}).json()
        return parse_prices(body)

    def positions(self, epic: str) -> list[dict]:
        out = []
        for item in self._req("GET", "/api/v1/positions").json().get("positions", []):
            pos, market = item.get("position", {}), item.get("market", {})
            if market.get("epic") == epic:
                out.append({"dealId": pos.get("dealId"), "direction": pos.get("direction"),
                            "size": float(pos.get("size", 0)), "level": float(pos.get("level", 0)),
                            "stopLevel": pos.get("stopLevel"), "upl": pos.get("upl"),
                            "created": pos.get("createdDateUTC") or pos.get("createdDate")})
        return out

    def open(self, epic: str, direction: str, size: float, stop_level: float | None) -> dict:
        payload = {"epic": epic, "direction": direction, "size": size, "guaranteedStop": False}
        if stop_level is not None:
            payload["stopLevel"] = round(stop_level, 2)
        ref = self._req("POST", "/api/v1/positions", json=payload).json().get("dealReference")
        return self.confirm(ref)

    def close(self, deal_id: str) -> dict:
        ref = self._req("DELETE", f"/api/v1/positions/{deal_id}").json().get("dealReference")
        return self.confirm(ref)

    def set_stop(self, deal_id: str, stop_level: float) -> None:
        self._req("PUT", f"/api/v1/positions/{deal_id}", json={"stopLevel": round(stop_level, 2)})

    def confirm(self, ref: str | None) -> dict:
        if not ref:
            raise RuntimeError("Capital.com no devolvio dealReference.")
        body = self._req("GET", f"/api/v1/confirms/{ref}").json()
        if body.get("dealStatus") not in (None, "ACCEPTED"):
            raise RuntimeError(f"Orden rechazada: {body.get('reason') or body}")
        return body


def parse_prices(body: dict) -> pd.DataFrame:
    rows = [
        {
            "time": p.get("snapshotTimeUTC") or p.get("snapshotTime"),
            "open": (p.get("openPrice") or {}).get("bid"),
            "high": (p.get("highPrice") or {}).get("bid"),
            "low": (p.get("lowPrice") or {}).get("bid"),
            "close": (p.get("closePrice") or {}).get("bid"),
        }
        for p in body.get("prices", [])
    ]
    df = pd.DataFrame(rows).dropna()
    if df.empty:
        return df
    df["time"] = pd.to_datetime(df["time"], utc=True)
    return df.set_index("time").astype(float).sort_index()


def closed_bars(df: pd.DataFrame, resolution: str, now: datetime) -> pd.DataFrame:
    """Quita la vela en formacion (inicio + duracion > ahora)."""
    minutes = RESOLUTION_MINUTES[resolution]
    end = df.index + pd.Timedelta(minutes=minutes)
    return df[end <= pd.Timestamp(now)]


def _utc(value) -> pd.Timestamp | None:
    if not value:
        return None
    try:
        t = pd.Timestamp(value)
    except (ValueError, TypeError):
        return None
    return t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")


def signal(df: pd.DataFrame, s: Settings, cfg: RiskConfig) -> dict:
    st = supertrend(df, s.period, s.factor)
    trend = int(st["trend"].iloc[-1])
    flips = np.flatnonzero((st["buy"] | st["sell"]).to_numpy())
    atr = float(rma_atr(df["high"].to_numpy(), df["low"].to_numpy(), df["close"].to_numpy(), s.period)[-1])
    line = float(st["supertrend"].iloc[-1])
    want = "BUY" if trend == 1 else "SELL"
    return {
        "want": want, "color": "VERDE" if trend == 1 else "ROJO",
        "signal_age_bars": int(len(st) - 1 - flips[-1]) if len(flips) else None,
        "last_closed_bar": str(df.index[-1]), "close": float(df["close"].iloc[-1]), "supertrend": line, "atr": atr,
        "stop": line - cfg.stop_atr * atr if want == "BUY" else line + cfg.stop_atr * atr,
    }


def plan(df: pd.DataFrame, positions: list[dict], equity: float, rules: dict, gates: dict,
         s: Settings, cfg: RiskConfig, now: datetime) -> dict:
    """Decision pura (testeable sin red). `gates` = {'news': {...}, 'breaker': str|None}."""
    d = signal(df, s, cfg)
    want, side = d["want"], (1 if d["want"] == "BUY" else -1)
    cfg_mkt = RiskConfig(**{**cfg.__dict__, "min_size": rules.get("min_size", cfg.min_size),
                            "size_step": rules.get("size_step", cfg.size_step)})
    opposite = [p for p in positions if p["direction"] != want]
    same = [p for p in positions if p["direction"] == want]
    n_max = max_units_for_equity(equity, cfg) if s.sizing == "risk" else 1
    actions: list[dict] = [{"type": "close", "dealId": p["dealId"]} for p in opposite]
    for p in same:  # el stop solo se mueve a favor
        old = p.get("stopLevel")
        if old is None or side * (d["stop"] - float(old)) > 0.009:
            actions.append({"type": "stop", "dealId": p["dealId"], "level": round(d["stop"], 2)})
    # precio de ejecucion estimado (compra al offer, venta al bid)
    px = rules.get("offer") if want == "BUY" else rules.get("bid")
    px = float(px) if px else d["close"]
    block = None
    if gates.get("breaker"):
        block = gates["breaker"]
    elif gates.get("news", {}).get("block"):
        block = "noticias: " + gates["news"]["reason"]
    elif side * (px - d["stop"]) <= 0:
        block = f"el precio ({px:.2f}) ya cruzo el stop de la señal ({d['stop']:.2f})"

    def sized():
        if s.sizing != "risk":
            return round_down(s.size, cfg_mkt.size_step), "tamaño fijo (BOT_SIZE)"
        return position_size(equity, px, d["stop"], n_max, sum(p["size"] for p in same), cfg_mkt)

    if not same:
        fresh = s.max_signal_age <= 0 or (d["signal_age_bars"] is not None and d["signal_age_bars"] < s.max_signal_age)
        if not fresh:
            d["decision"] = (f"ESPERAR: el cambio de color fue hace {d['signal_age_bars']} velas; "
                             f"solo se entra en las primeras {s.max_signal_age}")
        elif block:
            d["decision"] = f"NO ABRIR: {block}"
        else:
            size, why = sized()
            if size > 0:
                actions.append({"type": "open", "direction": want, "size": size, "stop": round(d["stop"], 2)})
                d["decision"] = f"ABRIR {want} {size} (limita: {why}; N max {n_max})"
            else:
                d["decision"] = f"NO ABRIR: {why}"
    else:
        newest = max(same, key=lambda p: str(p.get("created") or ""))
        bar_end = pd.Timestamp(df.index[-1]) + pd.Timedelta(minutes=RESOLUTION_MINUTES[s.resolution])
        created = _utc(newest.get("created"))
        new_bar = created is None or created < bar_end
        moved = side * (d["close"] - newest["level"]) >= cfg.add_every_atr * d["atr"]
        risk_ok = open_risk(same) <= equity * cfg.total_risk_pct / 100
        if s.sizing == "risk" and len(same) < n_max and moved and new_bar and risk_ok and not block:
            size, why = sized()
            if size > 0:
                actions.append({"type": "open", "direction": want, "size": size, "stop": round(d["stop"], 2), "add": True})
                d["decision"] = f"AGREGAR {want} {size} (posicion {len(same) + 1} de {n_max})"
            else:
                d["decision"] = f"MANTENER ({why})"
        else:
            why = ("ya hay N max" if len(same) >= n_max else "aun no avanza 1 ATR" if not moved
                   else "ya se agrego en esta vela" if not new_bar else "riesgo total al limite" if not risk_ok
                   else block or "")
            d["decision"] = f"MANTENER {len(same)} posicion(es) {want} ({why})"
    if opposite:
        d["decision"] = f"CERRAR {len(opposite)} posicion(es) contrarias · " + d["decision"]
    d.update({"actions": actions, "n_max": n_max, "equity": equity, "price": px, "block": block})
    return d


def load_state(path: str | None) -> dict:
    if not path or not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def save_state(path: str | None, state: dict) -> None:
    if path:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(state, fh, indent=2)


def breakers(state: dict, equity: float, now: datetime, cfg: RiskConfig) -> tuple[dict, str | None]:
    """Freno diario y de caida maxima (trader-risk). Necesita estado persistente."""
    day = pd.Timestamp(now).tz_convert("America/New_York").strftime("%Y-%m-%d")
    if state.get("day") != day:
        state.update({"day": day, "day_start_equity": equity})
    state["peak_equity"] = max(float(state.get("peak_equity", equity)), equity)
    if state.get("halted"):
        return state, f"pausado por caida maxima desde {state['halted']} (borra 'halted' del estado para reanudar)"
    if equity < state["peak_equity"] * (1 - cfg.max_drawdown_pct / 100):
        state["halted"] = str(pd.Timestamp(now))
        return state, f"caida de {cfg.max_drawdown_pct:g} % desde el maximo (${state['peak_equity']:,.2f})"
    if equity < state["day_start_equity"] * (1 - cfg.daily_loss_pct / 100):
        return state, f"perdida diaria mayor a {cfg.daily_loss_pct:g} % (inicio del dia ${state['day_start_equity']:,.2f})"
    return state, None


def check_preconditions(s: Settings) -> dict | None:
    if not s.enabled:
        return {"status": "deshabilitado", "detalle": "BOT_ENABLED no es 'true': no se hizo nada."}
    if s.environment not in BASE_URLS:
        raise RuntimeError(f"CAPITAL_ENV invalido: {s.environment}")
    if s.environment == "LIVE" and not s.allow_live:
        raise RuntimeError("CAPITAL_ENV=LIVE requiere BOT_ALLOW_LIVE=true (proteccion contra dinero real por error).")
    if not (s.api_key and s.identifier and s.password):
        raise RuntimeError("Faltan CAPITAL_API_KEY / CAPITAL_IDENTIFIER / CAPITAL_PASSWORD en los secretos.")
    return None


def run(s: Settings, now: datetime | None = None, api: "CapitalAPI | None" = None,
        calendar: tuple | None = None, cfg: RiskConfig | None = None, news_cfg: NewsConfig | None = None) -> dict:
    """Una pasada completa. Con `api` ya conectado (runner continuo) no hace login/logout."""
    now = now or datetime.now(timezone.utc)
    pre = check_preconditions(s)
    if pre:
        return pre
    cfg = cfg or RiskConfig.from_env()
    if s.emergency_stop_atr and os.environ.get("RISK_STOP_ATR") is None:
        cfg.stop_atr = s.emergency_stop_atr
    news_cfg = news_cfg or NewsConfig.from_env()
    own = api is None
    if own:
        api = CapitalAPI(s)
        api.login()
    try:
        df = closed_bars(api.candles(s.epic, s.resolution), s.resolution, now)
        if len(df) < s.period * 5:
            raise RuntimeError(f"Solo {len(df)} velas cerradas de {s.epic}; insuficiente para el Supertrend.")
        positions = api.positions(s.epic)
        eq = api.equity()
        rules = api.market_rules(s.epic)
        events, source = calendar if calendar is not None else fetch_calendar()
        news = check_news(now, events, source, news_cfg)
        state = load_state(s.state_file)
        state, brk = breakers(state, eq["equity"], now, cfg)
        save_state(s.state_file, state)
        d = plan(df, positions, eq["equity"], rules, {"news": news, "breaker": brk}, s, cfg, now)
        d.update({"env": s.environment, "epic": s.epic, "dry_run": s.dry_run, "cuenta": api.account_label,
                  "capital": eq, "news": news, "posiciones_antes": positions, "ejecutado": [],
                  "posiciones_despues": positions, "risk_pct": cfg.total_risk_pct})
        if s.dry_run:
            return d
        for act in d["actions"]:
            if act["type"] == "close":
                d["ejecutado"].append({"cerrar": act["dealId"], "resp": api.close(act["dealId"]).get("dealStatus")})
            elif act["type"] == "stop":
                api.set_stop(act["dealId"], act["level"])
                d["ejecutado"].append({"stop": act["dealId"], "nivel": act["level"]})
            elif act["type"] == "open":
                resp = api.open(s.epic, act["direction"], act["size"], act["stop"])
                deal = (resp.get("affectedDeals") or [{}])[0].get("dealId") or resp.get("dealId")
                d["ejecutado"].append({"abrir" if not act.get("add") else "agregar": act["direction"],
                                       "size": act["size"], "resp": resp.get("dealStatus"),
                                       "nivel": resp.get("level"), "stop": act["stop"], "dealId": deal})
        if d["ejecutado"]:
            d["posiciones_despues"] = api.positions(s.epic)
        return d
    finally:
        if own:
            api.logout()


def _summary(d: dict) -> str:
    if d.get("status") == "deshabilitado":
        return f"### Robot Supertrend\n{d['detalle']}\n"
    cap = d["capital"]
    nx = "; ".join(e.label() for e in d["news"].get("next", [])[:3]) or "ninguna en la semana"
    lines = [
        f"### Robot Supertrend {d['epic']} · {d['env']}{' · SIMULACION (dry run)' if d['dry_run'] else ''}",
        f"- Cuenta: **{d.get('cuenta', '?')}** · capital {cap['equity']:,.2f} {cap['currency']} "
        f"(balance {cap['balance']:,.2f}, abierto {cap['pl']:+,.2f}) · riesgo total {d['risk_pct']:g} % · N max {d['n_max']}",
        f"- Ultima vela cerrada: `{d['last_closed_bar']}` · cierre {d['close']:.2f} · precio ejecucion ~{d['price']:.2f}",
        f"- Supertrend: **{d['color']}** (linea {d['supertrend']:.2f}, ATR {d['atr']:.2f}) "
        f"· cambio de color hace {d['signal_age_bars']} velas · stop de la señal {d['stop']:.2f}",
        f"- Decision: **{d['decision']}**",
        f"- Noticias ({d['news'].get('source', '?')}): {d['news']['reason']} · proximas: {nx}",
        f"- Posiciones antes: {len(d['posiciones_antes'])} · Ejecutado: {json.dumps(d['ejecutado'], ensure_ascii=False)}",
    ]
    for p in d.get("posiciones_despues") or []:
        lines.append(f"- Posicion {d['epic']}: {p['direction']} {p['size']} @ {p['level']:.2f} · stop {p.get('stopLevel')} "
                     f"· P/L {p.get('upl')} · dealId `{p['dealId']}`")
    return "\n".join(lines) + "\n"


def main() -> int:
    s = Settings.from_env()
    try:
        result = run(s)
    except Exception as exc:  # el fallo debe verse en rojo en GitHub Actions
        print(f"ERROR: {exc}")
        return 1
    text = _summary(result)
    print(text)
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as fh:
            fh.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
