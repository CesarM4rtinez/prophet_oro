"""Backtest real (bar a bar, con capital/comisiones/position sizing) de la
estrategia WMA(14) + filtro RSI(14), usando la libreria `backtesting` -- misma
libreria y patron ya probados en el proyecto eth_dashboard
(core/backtest_engine.py). Las señales se precalculan UNA sola vez con
`strategy.generate_signals` (la MISMA funcion que usa el motor en vivo) y el
backtest solo las reproduce barra a barra -- no hay una segunda implementacion
de la logica de entradas/salidas."""
from __future__ import annotations

import pandas as pd
from backtesting import Strategy
from backtesting.lib import FractionalBacktest

from . import config
from .strategy import generate_signals


def _to_backtesting_df(df: pd.DataFrame) -> pd.DataFrame:
    return df.rename(columns={"open": "Open", "high": "High", "low": "Low", "close": "Close", "volume": "Volume"})


def _position_fraction(price: float, sl: float, risk_pct: float) -> float | None:
    """Fraccion de equity para arriesgar aproximadamente `risk_pct`% del capital
    dado el precio y el stop-loss (misma formula que eth_dashboard/core/backtest_engine.py)."""
    risk_dist = abs(price - sl)
    if risk_dist <= 0 or price <= 0:
        return None
    fraction = (risk_pct / 100) * price / risk_dist
    return float(min(0.99, max(0.01, fraction)))


def _make_strategy(signals: pd.DataFrame, risk_pct: float) -> type[Strategy]:
    signal_list = signals["signal"].tolist()
    sl_list = signals["stop_loss"].tolist()

    class WmaRsiStrategy(Strategy):
        def init(self) -> None:
            pass

        def next(self) -> None:
            idx = len(self.data) - 1
            if idx >= len(signal_list):
                return
            sig = signal_list[idx]
            # pd.isna() y no "sig is None": si la columna "signal" quedo con dtype
            # "str" (pandas infiere ese dtype cuando la mayoria de valores son
            # texto con huecos), los huecos vacios se representan como NaN, no
            # como None -- "sig is None" nunca los detectaba y el backtest se
            # saltaba señales completas (encontrado al comparar el conteo de
            # operaciones contra la maquina de estados con datos reales).
            if pd.isna(sig):
                return

            # El cierre por SL lo decide `generate_signals` (misma logica que el
            # motor en vivo), NO el parametro sl= de Backtesting.py: `FractionalBacktest`
            # reescala internamente Open/High/Low/Close por `fractional_unit` (1e-8 por
            # defecto) para simular tamaños fraccionarios, y un sl= en precio REAL sin
            # escalar queda a años luz de la serie escalada -- nunca se dispara (se
            # detecto al ver que el numero de trades no coincidia con los cierres de la
            # maquina de estados contra datos reales). Cerrar manualmente evita depender
            # de esa escala por completo.
            if sig == "SL_CLOSE":
                if self.position:
                    self.position.close()
                return

            sl = sl_list[idx]
            price = float(self.data.Close[-1])
            fraction = _position_fraction(price, sl, risk_pct)
            if fraction is None:
                return

            if sig in ("BUY_OPEN", "REVERSE_TO_LONG"):
                if self.position.is_short:
                    self.position.close()
                if not self.position:
                    self.buy(size=fraction)
            elif sig in ("SELL_OPEN", "REVERSE_TO_SHORT"):
                if self.position.is_long:
                    self.position.close()
                if not self.position:
                    self.sell(size=fraction)

    return WmaRsiStrategy


def run_backtest(
    df: pd.DataFrame,
    initial_cash: float = 10_000.0,
    commission_pct: float = 0.1,
    risk_pct: float = config.RISK_PCT_DEFAULT,
) -> dict:
    """Corre el backtest real sobre `df` (columnas open/high/low/close/volume) y
    devuelve stats de Backtesting.py, la tabla de operaciones, la curva de
    equity y las señales precalculadas (para graficarlas junto al backtest)."""
    signals = generate_signals(df)
    bt_df = _to_backtesting_df(signals[["open", "high", "low", "close", "volume"]])
    strategy_cls = _make_strategy(signals, risk_pct)

    # FractionalBacktest (no la clase Backtest plana) porque en Capital.com el
    # tamaño de una posicion CFD puede ser fraccionario (ej. 0.0093 BTC, visto en
    # produccion) -- la clase base solo permite unidades enteras y rechaza ordenes
    # en instrumentos caros (BTC) por "margen insuficiente" con un cash inicial
    # normal, algo que no refleja como se opera realmente via CFDs.
    # trade_on_close=True: `generate_signals` asume que la entrada se llena al
    # CIERRE de la misma vela del quiebro (`entry_price = close[i]`) y que el SL
    # ya vigila desde esa vela -- el valor por defecto de Backtesting.py (llenar
    # en la APERTURA de la vela siguiente) desalinea sus fills con los de la
    # maquina de estados y "pierde" señales (se detecto al comparar el conteo de
    # aperturas contra el numero de trades ejecutados con datos reales).
    bt = FractionalBacktest(
        bt_df, strategy_cls, cash=initial_cash, commission=commission_pct / 100,
        trade_on_close=True, finalize_trades=True, exclusive_orders=True,
    )
    stats = bt.run()

    return {
        "stats": stats,
        "trades": stats["_trades"].copy(),
        "equity_curve": stats["_equity_curve"]["Equity"].copy(),
        "signals": signals,
    }
