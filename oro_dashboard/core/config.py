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

# --- Estrategia institucional (SMC/ICT), core/smc_zones.py --------------------

# Cascada de temporalidades: mayor = sesgo, media = estructura, menor = entrada.
# El usuario pidio explicitamente sumar una temporalidad tipo 1D despues de que
# una barrida de liquidez en 5m/15m/1h (sin sesgo macro que la filtrara) genero
# una señal alcista falsa justo antes de una reversion.
ICT_BIAS_INTERVAL = "1d"
ICT_STRUCTURE_INTERVAL = "1h"
ICT_ENTRY_INTERVAL = "5m"
ICT_MIN_RR = 2.0
ICT_MANIPULATION_SL_ATR_MULT = 0.15
PROBABILITY_ANALOG_TOLERANCE = 0.5  # +/- 50% de la altura de zona relativa al ATR
PROBABILITY_RECENT_STRUCTURE_N = 30
PROBABILITY_RETEST_WARNING_PCT = 35.0
PROBABILITY_SIGNAL_TP_FRACTIONS = (0.2, 0.4, 0.6, 0.8, 1.0)

# --- Panel BI: cascadas de 2 temporalidades, core/mtf_signal.py ---------------

# Cada cascada es DOS temporalidades (deliberadamente distinta de la cascada de
# 3 de ICT_*: el usuario pidio explicitamente una regla mas simple y directa —
# direccion via continuacion de estructura, entrada via cualquier quiebre de
# estructura alineado con esa direccion). La segunda cascada (1h/15m) es la
# misma regla un nivel de temporalidad mas arriba que la primera (15m/5m),
# pedida explicitamente para comparar ambas en el mismo panel.
BI_CASCADES = (
    {"direction": "15m", "entry": "5m", "label": "15m → 5m"},
    {"direction": "1h", "entry": "15m", "label": "1h → 15m"},
)
# Ventana de "reciente" para el quiebre de entrada (en velas de esa
# temporalidad): un quiebre viejo ya no es un disparador de entrada valido,
# solo historia. Se reutiliza para ambas cascadas: 12 velas de 5m (~1h) o de
# 15m (~3h) son, en proporcion a su propia temporalidad de direccion, una
# ventana de "reciente" comparable.
BI_ENTRY_RECENT_BARS = 12
# Ventana (mas amplia) para la posicion de VISTA PREVIA del grafico: busca el
# quiebre valido mas reciente dentro de esta cantidad de velas de la
# temporalidad de entrada, en vez de exigir que sea el ULTIMO quiebre — a
# diferencia de la señal operable (BI_ENTRY_RECENT_BARS), esto es solo una
# referencia visual, no un gatillo.
BI_PREVIEW_LOOKBACK_BARS = 300
