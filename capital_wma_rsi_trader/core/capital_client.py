"""Cliente REST para Capital.com (broker de CFDs). No hay SDK oficial en Python:
wrapper propio sobre `requests`, verificado contra la documentacion publica de la
API v1 (mismo cliente ya probado en produccion en el proyecto eth_dashboard).

El login NUNCA ocurre automaticamente: es un paso explicito (`login()`) que la UI
dispara solo cuando el usuario pulsa "Conectar".
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import datetime

import pandas as pd
import requests
import streamlit as st

from . import config


class CapitalError(Exception):
    """Error generico de la API de Capital.com."""


class CapitalAuthError(CapitalError):
    pass


class CapitalSessionExpiredError(CapitalError):
    pass


class CapitalOrderRejectedError(CapitalError):
    pass


class CapitalRateLimitError(CapitalError):
    pass


@dataclass
class CapitalAccount:
    account_id: str
    account_name: str
    balance: float
    currency: str
    account_type: str
    deposit: float = 0.0
    profit_loss: float = 0.0
    available: float = 0.0


@dataclass
class CapitalPosition:
    deal_id: str
    epic: str
    instrument_name: str
    direction: str
    size: float
    open_level: float
    current_level: float
    profit_loss: float
    currency: str
    stop_level: float | None = None
    profit_level: float | None = None
    created_at: datetime | None = None


def _safe_json(response: requests.Response) -> dict:
    try:
        return response.json()
    except ValueError:
        return {}


def _parse_created_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        ts = pd.to_datetime(value, utc=True, errors="coerce")
    except (TypeError, ValueError):
        return None
    if pd.isna(ts):
        return None
    return ts.to_pydatetime()


class CapitalComClient:
    """Wrapper minimo sobre la API REST v1 de Capital.com (demo y real)."""

    def __init__(self, environment: str, api_key: str, identifier: str, password: str):
        environment = environment.upper()
        if environment not in config.CAPITAL_BASE_URLS:
            raise ValueError(f"Entorno invalido: {environment}")
        self.environment = environment
        self.base_url = config.CAPITAL_BASE_URLS[environment]
        self.api_key = api_key
        self.identifier = identifier
        self.password = password

        self._cst: str | None = None
        self._security_token: str | None = None
        self._last_activity: float = 0.0
        self.account_id: str | None = None
        self.account_currency: str | None = None

    @property
    def is_connected(self) -> bool:
        return bool(self._cst and self._security_token)

    def _headers(self, authenticated: bool = True) -> dict:
        headers = {"X-CAP-API-KEY": self.api_key, "Content-Type": "application/json"}
        if authenticated:
            if not self.is_connected:
                raise CapitalSessionExpiredError("No hay sesion activa. Pulsa 'Conectar' primero.")
            headers["CST"] = self._cst
            headers["X-SECURITY-TOKEN"] = self._security_token
        return headers

    def _request(self, method: str, path: str, authenticated: bool = True, **kwargs) -> requests.Response:
        url = f"{self.base_url}{path}"
        response = requests.request(method, url, headers=self._headers(authenticated), timeout=15, **kwargs)
        if response.status_code == 401 and authenticated:
            self._cst = self._security_token = None
            raise CapitalSessionExpiredError("Sesion expirada o invalida en Capital.com. Reconecta.")
        if response.status_code == 429:
            raise CapitalRateLimitError("Limite de solicitudes de Capital.com excedido, intenta en unos segundos.")
        if not response.ok:
            detail = _safe_json(response).get("errorCode", response.text[:300])
            raise CapitalError(f"Capital.com API error {response.status_code}: {detail}")
        self._last_activity = time.time()
        return response

    # -- sesion ---------------------------------------------------------------

    def login(self) -> dict:
        response = requests.post(
            f"{self.base_url}/api/v1/session",
            headers={"X-CAP-API-KEY": self.api_key, "Content-Type": "application/json"},
            json={"identifier": self.identifier, "password": self.password, "encryptedPassword": False},
            timeout=15,
        )
        if not response.ok:
            detail = _safe_json(response).get("errorCode", response.text[:300])
            raise CapitalAuthError(f"No se pudo iniciar sesion en Capital.com ({self.environment}): {detail}")

        self._cst = response.headers.get("CST")
        self._security_token = response.headers.get("X-SECURITY-TOKEN")
        if not self.is_connected:
            raise CapitalAuthError("Capital.com no devolvio tokens de sesion validos.")

        body = _safe_json(response)
        self.account_id = body.get("currentAccountId") or body.get("accountId")
        self.account_currency = body.get("currency")
        self._last_activity = time.time()
        return body

    def ping(self) -> None:
        self._request("GET", "/api/v1/ping")

    def keepalive_if_needed(self, threshold_seconds: int = config.SESSION_KEEPALIVE_SECONDS) -> None:
        if self.is_connected and time.time() - self._last_activity > threshold_seconds:
            self.ping()

    def logout(self) -> None:
        try:
            if self.is_connected:
                self._request("DELETE", "/api/v1/session")
        finally:
            self._cst = self._security_token = None

    # -- cuentas ---------------------------------------------------------------

    def list_accounts(self) -> list[CapitalAccount]:
        body = _safe_json(self._request("GET", "/api/v1/accounts"))
        accounts = []
        for a in body.get("accounts", []):
            bal = a.get("balance") or {}
            accounts.append(
                CapitalAccount(
                    account_id=a.get("accountId", ""),
                    account_name=a.get("accountName", ""),
                    balance=float(bal.get("balance", 0.0) or 0.0),
                    currency=a.get("currency", ""),
                    account_type=a.get("accountType", ""),
                    deposit=float(bal.get("deposit", 0.0) or 0.0),
                    profit_loss=float(bal.get("profitLoss", 0.0) or 0.0),
                    available=float(bal.get("available", 0.0) or 0.0),
                )
            )
        return accounts

    def get_account_by_name(self, name: str) -> CapitalAccount | None:
        target = name.strip().lower()
        for acc in self.list_accounts():
            if acc.account_name.strip().lower() == target:
                return acc
        return None

    def get_account_summary(self) -> CapitalAccount | None:
        """Cuenta actualmente activa (saldo, disponible y P/L abierto en tiempo real)."""
        for acc in self.list_accounts():
            if acc.account_id == self.account_id:
                return acc
        return None

    def switch_account(self, account_id: str) -> None:
        response = self._request("PUT", "/api/v1/session", json={"accountId": account_id})
        body = _safe_json(response)
        self._cst = response.headers.get("CST") or self._cst
        self._security_token = response.headers.get("X-SECURITY-TOKEN") or self._security_token
        self.account_id = account_id
        self.account_currency = body.get("currency", self.account_currency)

    # -- mercados ---------------------------------------------------------------

    def search_markets(self, search_term: str, asset_class: str | None = None, limit: int = 25) -> list[dict]:
        params = {"searchTerm": search_term} if search_term else {}
        body = _safe_json(self._request("GET", "/api/v1/markets", params=params))
        markets = body.get("markets", [])
        if asset_class:
            instrument_type = config.CAPITAL_ASSET_CLASSES.get(asset_class)
            markets = [m for m in markets if m.get("instrumentType") == instrument_type]
        return markets[:limit]

    def browse_markets(
        self, asset_class: str, search_term: str = "", limit: int = config.CAPITAL_MARKET_BROWSE_LIMIT
    ) -> list[dict]:
        """Lista instrumentos de una clase de activo.

        Si `search_term` viene vacio, Capital.com no ofrece un endpoint de "listar
        todos los instrumentos" sin termino de busqueda, asi que estas semillas se
        combinan (una a una) para mostrar una lista amplia y representativa.
        """
        if search_term:
            return self.search_markets(search_term, asset_class=asset_class, limit=limit)

        seeds = config.CAPITAL_PRESET_SEEDS.get(asset_class, [])
        seen_epics: set[str] = set()
        combined: list[dict] = []
        last_error: Exception | None = None
        for seed in seeds:
            if len(combined) >= limit:
                break
            try:
                results = self.search_markets(seed, asset_class=asset_class, limit=limit)
            except CapitalError as exc:
                last_error = exc
                continue
            for market in results:
                epic = market.get("epic")
                if epic and epic not in seen_epics:
                    seen_epics.add(epic)
                    combined.append(market)

        if not combined and last_error:
            raise last_error
        return combined[:limit]

    def get_candles(self, epic: str, resolution: str = config.DEFAULT_CAPITAL_RESOLUTION, max_points: int = 100) -> pd.DataFrame:
        body = _safe_json(
            self._request("GET", f"/api/v1/prices/{epic}", params={"resolution": resolution, "max": max_points})
        )
        rows = [
            {
                "time": p.get("snapshotTimeUTC") or p.get("snapshotTime"),
                "open": (p.get("openPrice") or {}).get("bid"),
                "high": (p.get("highPrice") or {}).get("bid"),
                "low": (p.get("lowPrice") or {}).get("bid"),
                "close": (p.get("closePrice") or {}).get("bid"),
                "volume": p.get("lastTradedVolume", 0),
            }
            for p in body.get("prices", [])
        ]
        df = pd.DataFrame(rows).dropna()
        if df.empty:
            return df
        # "snapshotTimeUTC"/"snapshotTime" son UTC real pero llegan sin sufijo de zona
        # horaria -- utc=True los marca tz-aware en vez de naive (evita mezclas
        # tz-naive/tz-aware si en el futuro se cruzan con otra fuente).
        df["time"] = pd.to_datetime(df["time"], utc=True)
        return df.set_index("time").astype(float)

    # -- posiciones y ordenes ---------------------------------------------------------------

    def get_open_positions(self) -> list[CapitalPosition]:
        body = _safe_json(self._request("GET", "/api/v1/positions"))
        positions = []
        for item in body.get("positions", []):
            pos, market = item.get("position", {}), item.get("market", {})
            positions.append(
                CapitalPosition(
                    deal_id=pos.get("dealId", ""),
                    epic=market.get("epic", ""),
                    instrument_name=market.get("instrumentName", market.get("epic", "")),
                    direction=pos.get("direction", ""),
                    size=float(pos.get("size", 0)),
                    open_level=float(pos.get("level", 0)),
                    current_level=float(market.get("bid") or market.get("offer") or 0),
                    profit_loss=float(pos.get("upl", 0) or 0),
                    currency=pos.get("currency", ""),
                    stop_level=float(pos["stopLevel"]) if pos.get("stopLevel") is not None else None,
                    profit_level=float(pos["profitLevel"]) if pos.get("profitLevel") is not None else None,
                    created_at=_parse_created_date(pos.get("createdDate") or pos.get("createdDateUTC")),
                )
            )
        return positions

    def place_order(
        self,
        epic: str,
        direction: str,
        size: float,
        stop_level: float | None = None,
        stop_distance: float | None = None,
        profit_level: float | None = None,
        profit_distance: float | None = None,
        guaranteed_stop: bool = False,
    ) -> str:
        direction = direction.upper()
        if direction not in ("BUY", "SELL"):
            raise ValueError("direction debe ser BUY o SELL")
        if stop_level is not None and stop_distance is not None:
            raise ValueError("Especifica stop_level O stop_distance, no ambos")
        if profit_level is not None and profit_distance is not None:
            raise ValueError("Especifica profit_level O profit_distance, no ambos")

        payload = {"epic": epic, "direction": direction, "size": size, "guaranteedStop": guaranteed_stop}
        if stop_level is not None:
            payload["stopLevel"] = stop_level
        if stop_distance is not None:
            payload["stopDistance"] = stop_distance
        if profit_level is not None:
            payload["profitLevel"] = profit_level
        if profit_distance is not None:
            payload["profitDistance"] = profit_distance

        body = _safe_json(self._request("POST", "/api/v1/positions", json=payload))
        deal_reference = body.get("dealReference")
        if not deal_reference:
            raise CapitalOrderRejectedError(f"Capital.com no devolvio dealReference: {body}")
        return deal_reference

    def confirm_deal(self, deal_reference: str) -> dict:
        body = _safe_json(self._request("GET", f"/api/v1/confirms/{deal_reference}"))
        status = body.get("dealStatus")
        if status and status != "ACCEPTED":
            raise CapitalOrderRejectedError(f"Orden rechazada por Capital.com: {body.get('reason', status)}")
        return body

    def close_position(self, deal_id: str) -> str:
        body = _safe_json(self._request("DELETE", f"/api/v1/positions/{deal_id}"))
        deal_reference = body.get("dealReference")
        if not deal_reference:
            raise CapitalError(f"Capital.com no devolvio dealReference al cerrar: {body}")
        return deal_reference

    def update_position(self, deal_id: str, stop_level: float | None = None, profit_level: float | None = None) -> str:
        """Modifica el stop/take-profit de una posicion ya abierta."""
        payload = {}
        if stop_level is not None:
            payload["stopLevel"] = stop_level
        if profit_level is not None:
            payload["profitLevel"] = profit_level
        if not payload:
            raise ValueError("Especifica al menos stop_level o profit_level")

        body = _safe_json(self._request("PUT", f"/api/v1/positions/{deal_id}", json=payload))
        deal_reference = body.get("dealReference")
        if not deal_reference:
            raise CapitalError(f"Capital.com no devolvio dealReference al modificar la posicion: {body}")
        return deal_reference


@st.cache_resource(show_spinner=False)
def get_client(environment: str, api_key: str, identifier: str, password: str) -> CapitalComClient:
    """Instancia (sin loguear) cacheada por Streamlit para sobrevivir reruns sin perder la sesion."""
    return CapitalComClient(environment, api_key, identifier, password)
