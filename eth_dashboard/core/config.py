"""Configuracion central: variables de entorno, catalogos de simbolos y constantes."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

APP_DIR = Path(__file__).resolve().parent.parent
load_dotenv(APP_DIR / ".env")

APP_TITLE = "ETH Trading Dashboard"
APP_ICON = "📈"

# --- Fuentes de datos de mercado (analitica) ---------------------------------

YFINANCE_SYMBOLS = {
    "ETH-USD": "Ethereum / USD",
    "BTC-USD": "Bitcoin / USD",
    "SOL-USD": "Solana / USD",
    "BNB-USD": "BNB / USD",
    "GC=F": "Oro (Gold) / USD",
}
DEFAULT_YFINANCE_SYMBOL = "ETH-USD"

CCXT_EXCHANGES = ["binance", "kraken", "coinbase", "bybit", "okx"]
DEFAULT_CCXT_EXCHANGE = "binance"

CCXT_SYMBOLS = {
    "ETH/USDT": "Ethereum / USDT",
    "BTC/USDT": "Bitcoin / USDT",
    "SOL/USDT": "Solana / USDT",
    "BNB/USDT": "BNB / USDT",
}
DEFAULT_CCXT_SYMBOL = "ETH/USDT"

# Intervalos ofrecidos en la UI -> (yfinance interval, ccxt timeframe, periodo yfinance sugerido)
# yfinance no tiene intervalo nativo "4h" (maximo intradiario nativo es "60m"): para
# ese caso se pide "60m" y se resamplea a 4h en `core.data_provider.get_ohlcv`
# (ver clave "resample_from").
INTERVALS = {
    "1m": {"yfinance": "1m", "ccxt": "1m", "yfinance_period": "7d", "ccxt_limit": 500},
    "5m": {"yfinance": "5m", "ccxt": "5m", "yfinance_period": "30d", "ccxt_limit": 500},
    "15m": {"yfinance": "15m", "ccxt": "15m", "yfinance_period": "30d", "ccxt_limit": 500},
    "30m": {"yfinance": "30m", "ccxt": "30m", "yfinance_period": "60d", "ccxt_limit": 500},
    "1h": {"yfinance": "60m", "ccxt": "1h", "yfinance_period": "60d", "ccxt_limit": 500},
    "4h": {"yfinance": "60m", "ccxt": "4h", "yfinance_period": "730d", "ccxt_limit": 500, "resample_from": "4h"},
    "1d": {"yfinance": "1d", "ccxt": "1d", "yfinance_period": "1y", "ccxt_limit": 500},
}
DEFAULT_INTERVAL = "15m"

# Toolbar de temporalidad agrupada por estilo de trading (pages/patterns.py)
TRADING_STYLE_INTERVALS = {
    "Scalping": ["1m"],
    "Intraday": ["15m", "30m"],
    "Swing": ["4h", "1d"],
}

# Refresco automatico (segundos) ofrecido en la UI. 0 = sin auto-refresco.
REFRESH_OPTIONS = {"Apagado": 0, "15 s": 15, "30 s": 30, "60 s": 60}

# --- Estrategia institucional (SMC/ICT) ---------------------------------------

# Cascade de temporalidades: mayor = sesgo, media = estructura, menor = entrada.
# (el video sugiere Diario/4H -> 1H/15M -> 5M/1M; se adapta a los intervalos que
# ya soportan de forma confiable tanto yfinance como ccxt)
ICT_BIAS_INTERVAL = "1d"
ICT_STRUCTURE_INTERVAL = "1h"
ICT_ENTRY_INTERVAL = "5m"

# Sesiones de mayor liquidez (horas UTC). Londres 2:00-5:00 AM y Nueva York
# 8:00 AM-12:00 PM, ambas en hora de Nueva York (UTC-4 / EDT) -> convertidas a UTC.
SESSION_LONDON_UTC = (6, 9)
SESSION_NEWYORK_UTC = (11, 16)

# Offset fijo usado para mostrar "hora de Nueva York" en el dashboard (UTC-4 / EDT,
# misma convencion que las ventanas de sesion de arriba — no ajusta por horario de
# invierno EST/UTC-5).
NY_UTC_OFFSET_HOURS = -4

# Activos prioritarios de la estrategia (alta volatilidad/volumen)
CAPITAL_PRIORITY_ASSETS = {
    "EUR/USD": {"asset_class": "Forex", "search_term": "EURUSD"},
    "Oro (XAU/USD)": {"asset_class": "Futuros / Materias Primas (CFD)", "search_term": "XAUUSD"},
}
DXY_YFINANCE_TICKER = "DX-Y.NYB"
ICT_MIN_RR = 2.0
ICT_MANIPULATION_SL_ATR_MULT = 0.15
ICT_RISK_PCT_DEFAULT = 1.0
DEFAULT_MAX_AUTO_TRADES_PER_DAY = 1
# Regla de 45 minutos: si una posicion abierta por el motor automatico no avanzo
# NADA a favor de su direccion en este tiempo, se cierra por completo (la estructura
# no tiene fuerza o va en contra). Si avanzo algo mas no llego a 1:1, se aplica
# break-even en vez de cerrarla (ver `render_breakeven_monitor` en pages/terminal.py).
AUTO_TIME_LIMIT_MINUTES = 45
PROBABILITY_ANALOG_TOLERANCE = 0.5  # +/- 50% de la altura de zona relativa al ATR
PROBABILITY_RECENT_STRUCTURE_N = 30
PROBABILITY_RETEST_WARNING_PCT = 35.0
# Umbral de probabilidad promedio (multi-timeframe, ya alineada) para mostrar una
# señal concreta de Entry/SL/TP1-5 en el panel "Probabilidad de la zona activa" —
# mismo corte que separa el tier "Buena" de "Aceptable" en `zone_probability`.
PROBABILITY_SIGNAL_MIN_AVG = 60.0
# Niveles de toma de parcial (TP1..TP5) como fraccion de la distancia entre el
# entry y el objetivo de la zona (zone["tp"]) — TP5 coincide con ese objetivo.
PROBABILITY_SIGNAL_TP_FRACTIONS = (0.2, 0.4, 0.6, 0.8, 1.0)

# --- Capital.com --------------------------------------------------------------

CAPITAL_BASE_URLS = {
    "DEMO": "https://demo-api-capital.backend-capital.com",
    "LIVE": "https://api-capital.backend-capital.com",
}

# Mapeo clase de activo (UI) -> instrumentType real de Capital.com
CAPITAL_ASSET_CLASSES = {
    "Forex": "CURRENCIES",
    "Cripto": "CRYPTOCURRENCIES",
    "Indices": "INDICES",
    "Futuros / Materias Primas (CFD)": "COMMODITIES",
}

# marketStatus real que devuelve Capital.com por instrumento (campo "marketStatus" en
# /api/v1/markets) -> (icono, etiqueta). Solo "TRADEABLE" acepta ordenes nuevas; el
# resto se muestra igualmente pero marcado como no operable ahora mismo.
CAPITAL_MARKET_STATUS_LABELS = {
    "TRADEABLE": ("✅", "Operable"),
    "EDITS_ONLY": ("⚠️", "Solo edicion (sin ordenes nuevas)"),
    "ON_AUCTION": ("⚠️", "En subasta"),
    "ON_AUCTION_NO_EDITS": ("⚠️", "En subasta (sin edicion)"),
    "OFFLINE": ("⛔", "Fuera de linea"),
    "SUSPENDED": ("⛔", "Suspendido"),
    "CLOSED": ("⛔", "Mercado cerrado"),
}

# Busquedas "semilla" por clase de activo: Capital.com no permite listar TODOS los
# instrumentos sin termino de busqueda, asi que estas semillas se combinan (una a una)
# para mostrar una lista amplia y representativa apenas se elige la clase de activo.
CAPITAL_PRESET_SEEDS = {
    "Forex": ["EUR", "GBP", "USD", "JPY", "AUD", "CHF", "CAD", "NZD"],
    "Cripto": ["BTC", "ETH", "SOL", "XRP", "ADA", "DOGE", "LTC", "BNB"],
    "Indices": ["US500", "US100", "US30", "UK100", "GER40", "JP225", "FRA40", "EU50"],
    "Futuros / Materias Primas (CFD)": ["GOLD", "SILVER", "OIL", "NATURALGAS", "COPPER", "WHEAT"],
}
CAPITAL_MARKET_BROWSE_LIMIT = 150

CAPITAL_RESOLUTIONS = ["MINUTE", "MINUTE_5", "MINUTE_15", "MINUTE_30", "HOUR", "HOUR_4", "DAY"]
DEFAULT_CAPITAL_RESOLUTION = "MINUTE_15"

# Seguridad de trading: valores por defecto, todos ajustables solo dentro de la sesion.
DEFAULT_MAX_AUTO_TRADES_PER_SESSION = 3
SESSION_KEEPALIVE_SECONDS = 240  # bien por debajo del timeout real de 10 min


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
