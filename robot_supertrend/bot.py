"""Robot Supertrend 10/3 (1h) para el CFD GOLD de Capital.com.

Reglas (las del usuario, sobre velas CERRADAS como "Espere al cierre de los
intervalos de tiempo" en TradingView):
- Supertrend pasa a VERDE -> COMPRA.
- Supertrend pasa a ROJO  -> VENTA.
- Al cambiar de color se cierra la posicion abierta y se abre la contraria.

Cada ejecucion (GitHub Actions, unos minutos despues del cierre de cada vela 1h):
1. Inicia sesion en Capital.com (DEMO por defecto) y cambia a la subcuenta indicada.
2. Descarga las velas 1h del propio Capital.com (precio bid, el que muestra su grafico),
   descarta la vela en formacion y calcula el Supertrend con
   `oro_dashboard/core/supertrend.py` (el mismo codigo del dashboard).
3. Compara la direccion vigente con la posicion abierta en el instrumento:
   - posicion contraria -> la cierra y abre la nueva direccion;
   - sin posicion -> abre SOLO si el cambio de color ocurrio en las ultimas
     `BOT_MAX_SIGNAL_AGE` velas (no entra a mitad de una tendencia vieja);
   - misma direccion -> no hace nada (solo mueve el stop de emergencia).
   El estado sale del broker, no de un archivo: repetir una ejecucion es seguro.
4. Stop de emergencia en el broker = linea Supertrend -/+ `BOT_EMERGENCY_STOP_ATR`
   ATR, por si una ejecucion falla o el precio se dispara entre dos revisiones.

Seguridad:
- Sin `BOT_ENABLED=true` no hace nada. `BOT_DRY_RUN=true` calcula y registra sin
  enviar ordenes. Operar en LIVE exige ademas `BOT_ALLOW_LIVE=true`.
- Las claves se leen SOLO de variables de entorno (GitHub Secrets); nunca se
  escriben en el repositorio ni en los registros.
- Gestiona TODAS las posiciones del instrumento en la cuenta elegida: usa una
  subcuenta dedicada al robot y no operes GOLD a mano en ella.
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
from core.supertrend import rma_atr, supertrend  # noqa: E402  (mismo codigo que el dashboard)

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
            max_signal_age=int(_env("BOT_MAX_SIGNAL_AGE", "3") or 3),
            emergency_stop_atr=float(_env("BOT_EMERGENCY_STOP_ATR", "1.0") or 1.0),
            dry_run=_flag("BOT_DRY_RUN", False),
            enabled=_flag("BOT_ENABLED", False),
            allow_live=_flag("BOT_ALLOW_LIVE", False),
        )


class CapitalAPI:
    """Cliente REST minimo de Capital.com (mismas llamadas que
    capital_wma_rsi_trader/core/capital_client.py, sin dependencia de Streamlit)."""

    def __init__(self, s: Settings):
        self.s = s
        self.base = BASE_URLS[s.environment]
        self.cst = self.token = None

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

    def logout(self) -> None:
        try:
            if self.cst:
                self._req("DELETE", "/api/v1/session")
        except RuntimeError:
            pass

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
                            "stopLevel": pos.get("stopLevel"), "upl": pos.get("upl")})
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


def decide(df: pd.DataFrame, positions: list[dict], s: Settings) -> dict:
    """Decision pura (testeable sin red): que hacer dado el Supertrend y las posiciones."""
    st = supertrend(df, s.period, s.factor)
    trend = int(st["trend"].iloc[-1])
    want = "BUY" if trend == 1 else "SELL"
    flips = np.flatnonzero((st["buy"] | st["sell"]).to_numpy())
    age = int(len(st) - 1 - flips[-1]) if len(flips) else None
    atr = float(rma_atr(df["high"].to_numpy(), df["low"].to_numpy(), df["close"].to_numpy(), s.period)[-1])
    line = float(st["supertrend"].iloc[-1])
    stop = None
    if s.emergency_stop_atr > 0:
        stop = line - s.emergency_stop_atr * atr if want == "BUY" else line + s.emergency_stop_atr * atr

    to_close = [p for p in positions if p["direction"] != want]
    same = [p for p in positions if p["direction"] == want]
    fresh = age is not None and age < s.max_signal_age
    if to_close:
        action = "DAR_VUELTA"
    elif same:
        action = "MANTENER"
    elif fresh:
        action = "ABRIR"
    else:
        action = "ESPERAR"
    return {
        "want": want, "color": "VERDE" if trend == 1 else "ROJO", "signal_age_bars": age,
        "last_closed_bar": str(df.index[-1]), "close": float(df["close"].iloc[-1]),
        "supertrend": line, "atr": atr, "emergency_stop": stop, "action": action,
        "to_close": [p["dealId"] for p in to_close], "keep": [p["dealId"] for p in same],
    }


def run(s: Settings, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    if not s.enabled:
        return {"status": "deshabilitado", "detalle": "BOT_ENABLED no es 'true': no se hizo nada."}
    if s.environment not in BASE_URLS:
        raise RuntimeError(f"CAPITAL_ENV invalido: {s.environment}")
    if s.environment == "LIVE" and not s.allow_live:
        raise RuntimeError("CAPITAL_ENV=LIVE requiere BOT_ALLOW_LIVE=true (proteccion contra dinero real por error).")
    if not (s.api_key and s.identifier and s.password):
        raise RuntimeError("Faltan CAPITAL_API_KEY / CAPITAL_IDENTIFIER / CAPITAL_PASSWORD en los secretos.")

    api = CapitalAPI(s)
    api.login()
    try:
        df = closed_bars(api.candles(s.epic, s.resolution), s.resolution, now)
        if len(df) < s.period * 5:
            raise RuntimeError(f"Solo {len(df)} velas cerradas de {s.epic}; insuficiente para el Supertrend.")
        positions = api.positions(s.epic)
        d = decide(df, positions, s)
        d.update({"env": s.environment, "epic": s.epic, "size": s.size, "dry_run": s.dry_run,
                  "posiciones_antes": positions, "ejecutado": []})
        if s.dry_run:
            return d
        if d["action"] == "DAR_VUELTA":
            for deal_id in d["to_close"]:
                d["ejecutado"].append({"cerrar": deal_id, "resp": api.close(deal_id).get("dealStatus")})
        if d["action"] == "ABRIR" or (d["action"] == "DAR_VUELTA" and not d["keep"]):
            resp = api.open(s.epic, d["want"], s.size, d["emergency_stop"])
            d["ejecutado"].append({"abrir": d["want"], "size": s.size, "resp": resp.get("dealStatus"),
                                   "nivel": resp.get("level")})
        elif d["action"] == "MANTENER" and d["emergency_stop"] is not None:
            for p in positions:
                if p["dealId"] in d["keep"]:
                    old = p.get("stopLevel")
                    better = old is None or (d["want"] == "BUY" and d["emergency_stop"] > float(old)) or (
                        d["want"] == "SELL" and d["emergency_stop"] < float(old))
                    if better:  # el stop solo se mueve a favor, nunca se aleja
                        api.set_stop(p["dealId"], d["emergency_stop"])
                        d["ejecutado"].append({"stop": p["dealId"], "nivel": round(d["emergency_stop"], 2)})
        return d
    finally:
        api.logout()


def _summary(d: dict) -> str:
    if d.get("status") == "deshabilitado":
        return f"### Robot Supertrend\n{d['detalle']}\n"
    lines = [
        f"### Robot Supertrend {d['epic']} · {d['env']}{' · SIMULACION (dry run)' if d['dry_run'] else ''}",
        f"- Ultima vela cerrada: `{d['last_closed_bar']}` · cierre {d['close']:.2f}",
        f"- Supertrend: **{d['color']}** (linea {d['supertrend']:.2f}, ATR {d['atr']:.2f}) "
        f"· cambio de color hace {d['signal_age_bars']} velas",
        f"- Accion: **{d['action']}** → direccion {d['want']} · tamaño {d['size']}",
        f"- Stop de emergencia: {d['emergency_stop']:.2f}" if d["emergency_stop"] is not None else "- Sin stop de emergencia",
        f"- Posiciones antes: {len(d['posiciones_antes'])} · Ejecutado: {json.dumps(d['ejecutado'], ensure_ascii=False)}",
    ]
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
