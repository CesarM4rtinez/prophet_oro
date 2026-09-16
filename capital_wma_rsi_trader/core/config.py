"""Configuracion central: variables de entorno, catalogos de Capital.com y parametros
de la estrategia WMA(14) + filtro RSI(14)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

APP_DIR = Path(__file__).resolve().parent.parent
load_dotenv(APP_DIR / ".env")

APP_TITLE = "WMA/RSI Intraday Trader"
APP_ICON = "📐"

# --- Estrategia: WMA(14) + filtro de zonas RSI(14) ----------------------------

WMA_PERIOD = 14
RSI_PERIOD = 14
RSI_BUY_LEVEL = 40.0   # cruce hacia abajo arma la compra
RSI_SELL_LEVEL = 60.0  # cruce hacia arriba arma la venta
# Pivote simple (1 vela a cada lado) para ubicar el minimo/maximo previo mas
# cercano al momento de la entrada -- deliberadamente mas rapido/reactivo que un
# swing SMC confirmado con velas futuras (no serviria para un SL en vivo).
PIVOT_LOOKBACK = 3

# Temporalidad SUGERIDA por clase de activo (editable en la UI, no obligatoria).
CAPITAL_RESOLUTIONS = ["MINUTE", "MINUTE_5", "MINUTE_15", "MINUTE_30", "HOUR", "HOUR_4", "DAY"]
DEFAULT_CAPITAL_RESOLUTION = "MINUTE_15"
SUGGESTED_RESOLUTION_BY_CLASS = {
    "Indices": "MINUTE_5",
    "Forex": "MINUTE_5",
    "Cripto": "MINUTE_5",
    "Futuros / Materias Primas (CFD)": "MINUTE_15",
}

# Seguridad de ejecucion (operativas, no forman parte de la logica de señales):
DEFAULT_MAX_AUTO_TRADES_PER_SESSION = 10
SESSION_KEEPALIVE_SECONDS = 240  # bien por debajo del timeout real de 10 min
RISK_PCT_DEFAULT = 1.0  # % del saldo arriesgado por operacion (tamaño sugerido / backtest)

# --- Capital.com --------------------------------------------------------------

CAPITAL_BASE_URLS = {
    "DEMO": "https://demo-api-capital.backend-capital.com",
    "LIVE": "https://api-capital.backend-capital.com",
}

# Mapeo clase de activo (UI) -> instrumentType real de Capital.com
CAPITAL_ASSET_CLASSES = {
    "Indices": "INDICES",
    "Forex": "CURRENCIES",
    "Cripto": "CRYPTOCURRENCIES",
    "Futuros / Materias Primas (CFD)": "COMMODITIES",
}

# Busquedas "semilla" por clase de activo: Capital.com no permite listar TODOS los
# instrumentos sin termino de busqueda, asi que estas semillas se combinan (una a
# una) para mostrar una lista amplia y representativa apenas se elige la clase.
CAPITAL_PRESET_SEEDS = {
    "Indices": ["US500", "US100", "US30", "UK100", "GER40", "JP225", "FRA40", "EU50"],
    "Forex": ["EUR", "GBP", "USD", "JPY", "AUD", "CHF", "CAD", "NZD"],
    "Cripto": ["BTC", "ETH", "SOL", "XRP", "ADA", "DOGE", "LTC", "BNB"],
    "Futuros / Materias Primas (CFD)": ["GOLD", "SILVER", "OIL", "NATURALGAS", "COPPER", "WHEAT"],
}
CAPITAL_MARKET_BROWSE_LIMIT = 150

# marketStatus real que devuelve Capital.com por instrumento -> (icono, etiqueta).
CAPITAL_MARKET_STATUS_LABELS = {
    "TRADEABLE": ("✅", "Operable"),
    "EDITS_ONLY": ("⚠️", "Solo edicion (sin ordenes nuevas)"),
    "ON_AUCTION": ("⚠️", "En subasta"),
    "ON_AUCTION_NO_EDITS": ("⚠️", "En subasta (sin edicion)"),
    "OFFLINE": ("⛔", "Fuera de linea"),
    "SUSPENDED": ("⛔", "Suspendido"),
    "CLOSED": ("⛔", "Mercado cerrado"),
}


@dataclass(frozen=True)
class CapitalCredentials:
    api_key: str
    identifier: str
    password: str
    default_account_name: str
    default_environment: str


def get_capital_credentials() -> CapitalCredentials:
    return CapitalCredentials(
        api_key=os.getenv("CAPITAL_API_KEY", ""),
        identifier=os.getenv("CAPITAL_API_USER", ""),
        password=os.getenv("CAPITAL_API_PASSWORD", ""),
        default_account_name=os.getenv("CAPITAL_ACCOUNT_NAME", "CDFs"),
        default_environment=os.getenv("CAPITAL_DEFAULT_ENV", "DEMO").upper(),
    )


def capital_credentials_present() -> bool:
    creds = get_capital_credentials()
    return bool(creds.api_key and creds.identifier and creds.password)
