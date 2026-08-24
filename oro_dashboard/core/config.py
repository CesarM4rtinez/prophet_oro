"""Configuracion central: simbolo fijo (PAXG-USD como proxy de XAU/USD), rutas e intervalos."""
from __future__ import annotations

from pathlib import Path

APP_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = APP_DIR.parent

APP_TITLE = "Oro (XAU/USD) — Dashboard Predictivo"
APP_ICON = "🥇"

# PAXG-USD es el unico ticker de oro que yfinance sirve con datos reales de spot:
# token respaldado 1:1 por oro fisico LBMA, sigue el spot XAU/USD real. "GC=F"
# (futuros) y "XAU-USD"/"XAUUSD" devuelven datos vacios, casi vacios o con prima
# de futuros — verificado en proyecciones_oro_prophet.ipynb.
SYMBOL = "PAXG-USD"
SYMBOL_LABEL = "XAUUSD"

# Calendario economico FTMO: vive en la raiz del repo (dato compartido, no codigo),
# se actualiza manualmente por fuera de esta app.
CALENDAR_PATH = REPO_ROOT / "calendario_economico_ftmo" / "economic_calendar.xlsx"

# Intervalos ofrecidos en la UI -> (periodo yfinance sugerido, intervalo yfinance)
INTERVALS = {
    "5m": {"period": "30d", "interval": "5m"},
    "15m": {"period": "30d", "interval": "15m"},
    "1h": {"period": "180d", "interval": "60m"},
    "1d": {"period": "2y", "interval": "1d"},
}

# Refresco automatico (segundos) ofrecido en la UI. 0 = sin auto-refresco.
REFRESH_OPTIONS = {"Apagado": 0, "30 s": 30, "60 s": 60, "5 min": 300}
DEFAULT_REFRESH_LABEL = "60 s"

# Sesiones de mayor liquidez (horas UTC), misma convencion que eth_dashboard.
SESSION_LONDON_UTC = (6, 9)
SESSION_NEWYORK_UTC = (11, 16)
NY_UTC_OFFSET_HOURS = -4

# Killzone de Nueva York (celda 12 del notebook): ventana de mayor liquidez/movimiento
# direccional del dia (apertura NY + solape con Londres).
KILLZONE_NY_START = "08:00"
KILLZONE_NY_END = "12:00"
KILLZONE_TZ = "America/New_York"

# Estructura multi-temporalidad (celda 17)
SWING_LOOKBACK = 3
STRUCTURE_RESULT_WINDOW = 40
STRUCTURE_CONTINUATION_THRESHOLD_PCT = 0.3
