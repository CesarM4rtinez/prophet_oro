"""Maquina de estados de la estrategia intradia: WMA(14) + filtro de zonas RSI(14),
tal como fue especificada -- el filtro RSI habilita la posibilidad de operar
mientras el RSI esta POR FUERA de la zona neutra (< 40 para compra, > 60 para
venta); el disparo real ocurre solo cuando, con el filtro habilitado, la WMA
quiebra de direccion (minimo/maximo local). Mientras el RSI esta en la zona
neutra (40-60) cualquier quiebro de la WMA se ignora por completo.

Nota de diseño (importante, verificada contra datos reales antes de fijar esta
version): la primera lectura de la especificacion -- "el cruce de 40/60 ARMA la
posibilidad, y esa arma permanece activa aunque el RSI vuelva a 40-60 hasta que
la WMA quiebre" -- se probo contra velas reales de Capital.com y disparaba
señales constantemente con el RSI ya de vuelta en 45-56 (zona neutra), lo que
contradice el objetivo explicito de la estrategia ("el filtro RSI debe mantener
al sistema fuera de mercado la mayor parte del tiempo" en rangos). Por eso el
filtro aqui se evalua como una condicion CONTINUA en la misma vela del quiebro
(RSI < 40 o > 60 EN ESE MOMENTO, no "toco 40/60 en algun punto anterior") -- en
datos reales esto deja al RSI en zona neutra ~55% del tiempo, y solo en el resto
puede dispararse una entrada, coincidiendo con la intencion declarada del sistema.

Funcion PURA de pandas (sin Streamlit ni broker) -- la usan tanto el motor en vivo
(core/engine.py) como el backtest (core/backtest.py), asi la logica de señales
vive en un solo lugar.
"""
from __future__ import annotations

import pandas as pd

from . import config
from .indicators import rsi as compute_rsi
from .indicators import wma as compute_wma
from .indicators import wma_direction
from .swings import nearest_prior_pivot_high, nearest_prior_pivot_low


def generate_signals(
    df: pd.DataFrame,
    wma_period: int = config.WMA_PERIOD,
    rsi_period: int = config.RSI_PERIOD,
    buy_level: float = config.RSI_BUY_LEVEL,
    sell_level: float = config.RSI_SELL_LEVEL,
    pivot_lookback: int = config.PIVOT_LOOKBACK,
) -> pd.DataFrame:
    """Corre la maquina de estados bar a bar sobre `df` (columnas open/high/low/
    close). Devuelve una copia de `df` con columnas agregadas:

    - `wma`, `rsi`, `wma_dir` (1 ascendente / -1 descendente / 0 plana/sin dato).
    - `rsi_bias`: zona del filtro EN esa vela, condicion continua ("buy" si
      `rsi < buy_level`, "sell" si `rsi > sell_level`, "none" en la zona neutra).
    - `position`: posicion vigente AL CIERRE de esa vela ("flat"/"long"/"short").
    - `stop_loss`, `entry_price`: nivel/precio de la posicion vigente (None si flat).
    - `signal`: evento ocurrido en esa vela especifica -- "BUY_OPEN", "SELL_OPEN",
      "SL_CLOSE", "REVERSE_TO_SHORT", "REVERSE_TO_LONG", o None.
    """
    out = df.copy()
    out["wma"] = compute_wma(out["close"], wma_period)
    out["rsi"] = compute_rsi(out["close"], rsi_period)
    out["wma_dir"] = wma_direction(out["wma"])
    out["rsi_bias"] = "none"
    out.loc[out["rsi"] < buy_level, "rsi_bias"] = "buy"
    out.loc[out["rsi"] > sell_level, "rsi_bias"] = "sell"

    n = len(out)
    rsi_bias_vals = out["rsi_bias"].to_numpy()
    wma_dir_vals = out["wma_dir"].to_numpy()
    low = out["low"].to_numpy()
    high = out["high"].to_numpy()
    close = out["close"].to_numpy()

    position_col: list[str | None] = [None] * n
    stop_loss_col: list[float | None] = [None] * n
    entry_price_col: list[float | None] = [None] * n
    signal_col: list[str | None] = [None] * n

    position = "flat"
    stop_loss: float | None = None
    entry_price: float | None = None
    last_wma_dir = 0  # ultima direccion NO-CERO vista (ignora tramos planos intermedios)

    for i in range(n):
        rsi_bias = rsi_bias_vals[i]

        # Quiebro de la WMA en esta vela (minimo/maximo local)
        flip_up = flip_down = False
        d = wma_dir_vals[i]
        if d != 0:
            if last_wma_dir != 0 and d != last_wma_dir:
                flip_up, flip_down = d == 1, d == -1
            last_wma_dir = d

        signal = None

        if position == "flat":
            if rsi_bias == "buy" and flip_up:
                sl = nearest_prior_pivot_low(out, i, pivot_lookback)
                if sl is not None and sl < close[i]:
                    position, entry_price, stop_loss, signal = "long", close[i], sl, "BUY_OPEN"
            elif rsi_bias == "sell" and flip_down:
                sl = nearest_prior_pivot_high(out, i, pivot_lookback)
                if sl is not None and sl > close[i]:
                    position, entry_price, stop_loss, signal = "short", close[i], sl, "SELL_OPEN"

        elif position == "long":
            if low[i] <= stop_loss:
                position, entry_price, stop_loss, signal = "flat", None, None, "SL_CLOSE"
            elif rsi_bias == "sell" and flip_down:
                sl = nearest_prior_pivot_high(out, i, pivot_lookback)
                if sl is not None and sl > close[i]:
                    position, entry_price, stop_loss, signal = "short", close[i], sl, "REVERSE_TO_SHORT"

        elif position == "short":
            if high[i] >= stop_loss:
                position, entry_price, stop_loss, signal = "flat", None, None, "SL_CLOSE"
            elif rsi_bias == "buy" and flip_up:
                sl = nearest_prior_pivot_low(out, i, pivot_lookback)
                if sl is not None and sl < close[i]:
                    position, entry_price, stop_loss, signal = "long", close[i], sl, "REVERSE_TO_LONG"

        position_col[i] = position
        stop_loss_col[i] = stop_loss
        entry_price_col[i] = entry_price
        signal_col[i] = signal

    out["position"] = position_col
    out["stop_loss"] = stop_loss_col
    out["entry_price"] = entry_price_col
    # dtype=object explicito: sin esto, pandas puede inferir dtype "str" para esta
    # columna (mezcla de None y texto) y representar los huecos vacios como NaN en
    # vez de None -- "signal is None" dejaria de detectarlos (encontrado al
    # verificar el backtest contra datos reales, ver core/backtest.py).
    out["signal"] = pd.Series(signal_col, index=out.index, dtype=object)
    return out


def current_state(signals: pd.DataFrame) -> dict:
    """Resumen del estado vigente en la ULTIMA vela -- lo consume tanto la
    tarjeta de estado del Terminal como el motor semi-automatico."""
    if signals.empty:
        return {"position": "flat", "rsi_bias": "none", "wma_dir": 0, "stop_loss": None, "entry_price": None}
    last = signals.iloc[-1]
    return {
        "position": last["position"],
        "rsi_bias": last["rsi_bias"],
        "wma_dir": int(last["wma_dir"]),
        "stop_loss": last["stop_loss"],
        "entry_price": last["entry_price"],
        "signal": last["signal"],
    }
