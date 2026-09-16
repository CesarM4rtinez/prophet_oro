"""Backtesting historico real (Backtesting.py) de las estrategias del dashboard.

A diferencia de las estadisticas ad-hoc de `core/smc_zones.py` (¿esta zona
historicamente continuo?), esto simula capital, comisiones y position sizing real
barra a barra, produciendo una curva de equity y metricas de riesgo/retorno
(Sharpe, drawdown maximo, etc.) via la libreria `backtesting`.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from backtesting import Backtest, Strategy

from . import config
from .scalping import WEIGHTS, compute_indicators
from .smc_zones import historical_qualified_setups

STRATEGIES = ["SMC Institucional", "Scalping (score)"]


def _to_backtesting_df(df: pd.DataFrame) -> pd.DataFrame:
    return df.rename(columns={"open": "Open", "high": "High", "low": "Low", "close": "Close", "volume": "Volume"})


def _position_fraction(price: float, sl: float, risk_pct: float) -> float | None:
    """Fraccion de equity (lo que espera `size` en Backtesting.py) para arriesgar
    aproximadamente `risk_pct`% del capital dado el precio y el stop-loss."""
    risk_dist = abs(price - sl)
    if risk_dist <= 0 or price <= 0:
        return None
    fraction = (risk_pct / 100) * price / risk_dist
    return float(min(0.99, max(0.01, fraction)))


def vectorized_scalping_score(ind: pd.DataFrame) -> pd.Series:
    """Vectoriza la formula de `core.scalping.score_last` sobre toda la serie —
    mismo resultado, sin llamar fila por fila (mucho mas rapido para un backtest)."""
    atr_ref = ind["atr14"].where((ind["atr14"] > 0) & ind["atr14"].notna(), ind["close"] * 0.01)

    ema_component = np.tanh((ind["ema9"] - ind["ema50"]) / atr_ref)
    rsi_component = ((ind["rsi14"] - 50) / 50).fillna(0.0)
    macd_component = np.tanh((ind["macd"] - ind["macd_signal"]) / atr_ref).where(ind["macd"].notna(), 0.0)
    band_width = (ind["bb_upper"] - ind["bb_mid"]).where(ind["bb_mid"].notna(), atr_ref)
    band_width = band_width.where(band_width != 0, atr_ref)
    bollinger_component = ((ind["close"] - ind["bb_mid"]) / band_width).clip(-1, 1).where(ind["bb_mid"].notna(), 0.0)
    stoch_component = ((ind["stoch_k"] - 50) / 50).where(ind["stoch_k"].notna(), 0.0)

    raw_score = (
        WEIGHTS["ema"] * ema_component
        + WEIGHTS["rsi"] * rsi_component
        + WEIGHTS["macd"] * macd_component
        + WEIGHTS["bollinger"] * bollinger_component
        + WEIGHTS["stoch"] * stoch_component
    )
    rel_vol = ind["rel_volume"].fillna(1.0).clip(0.5, 2.0)
    return (raw_score * rel_vol).clip(-1, 1)


def _make_smc_strategy(entries_by_bar: dict[int, dict], risk_pct: float) -> type[Strategy]:
    class _SMCBacktestStrategy(Strategy):
        def init(self) -> None:
            pass

        def next(self) -> None:
            if self.position:
                return
            idx = len(self.data) - 1
            entry = entries_by_bar.get(idx)
            if entry is None:
                return
            price = float(self.data.Close[-1])
            fraction = _position_fraction(price, entry["sl"], risk_pct)
            if fraction is None:
                return
            if entry["direction"] == "BUY" and entry["sl"] < price < entry["tp"]:
                self.buy(sl=entry["sl"], tp=entry["tp"], size=fraction)
            elif entry["direction"] == "SELL" and entry["tp"] < price < entry["sl"]:
                self.sell(sl=entry["sl"], tp=entry["tp"], size=fraction)

    return _SMCBacktestStrategy


def _make_scalping_strategy(
    scores: pd.Series, sl_series: pd.Series, tp_series: pd.Series, threshold: float, risk_pct: float
) -> type[Strategy]:
    class _ScalpingBacktestStrategy(Strategy):
        def init(self) -> None:
            pass

        def next(self) -> None:
            if self.position:
                return
            idx = len(self.data) - 1
            if idx >= len(scores):
                return
            score = scores.iloc[idx]
            sl, tp = sl_series.iloc[idx], tp_series.iloc[idx]
            if pd.isna(score) or pd.isna(sl) or pd.isna(tp):
                return
            price = float(self.data.Close[-1])
            fraction = _position_fraction(price, float(sl), risk_pct)
            if fraction is None:
                return
            if score >= threshold and sl < price < tp:
                self.buy(sl=float(sl), tp=float(tp), size=fraction)
            elif score <= -threshold and tp < price < sl:
                self.sell(sl=float(sl), tp=float(tp), size=fraction)

    return _ScalpingBacktestStrategy


def run_backtest(
    df: pd.DataFrame,
    strategy_name: str,
    initial_cash: float = 10_000.0,
    commission_pct: float = 0.1,
    risk_pct: float = config.ICT_RISK_PCT_DEFAULT,
    scalping_threshold: float = 0.5,
    lookback: int = 5,
) -> dict:
    """Corre un backtest real con Backtesting.py sobre `df` (columnas open/high/low/
    close/volume) y devuelve stats, tabla de operaciones y curva de equity."""
    bt_df = _to_backtesting_df(df)

    if strategy_name == STRATEGIES[0]:
        setups = historical_qualified_setups(df, lookback=lookback)
        entries_by_bar = {s["entry_idx"]: s for s in setups}
        strategy_cls = _make_smc_strategy(entries_by_bar, risk_pct)
    else:
        indicators = compute_indicators(df)
        scores = vectorized_scalping_score(indicators)
        atr14 = indicators["atr14"]
        risk = 1.5 * atr14
        sl_buy, tp_buy = indicators["close"] - risk, indicators["close"] + config.ICT_MIN_RR * risk
        sl_sell, tp_sell = indicators["close"] + risk, indicators["close"] - config.ICT_MIN_RR * risk
        is_buy_side = scores >= 0
        sl_series = sl_buy.where(is_buy_side, sl_sell)
        tp_series = tp_buy.where(is_buy_side, tp_sell)
        strategy_cls = _make_scalping_strategy(scores, sl_series, tp_series, scalping_threshold, risk_pct)

    bt = Backtest(
        bt_df, strategy_cls, cash=initial_cash, commission=commission_pct / 100,
        finalize_trades=True, exclusive_orders=True,
    )
    stats = bt.run()
    return {"stats": stats, "trades": stats["_trades"], "equity_curve": stats["_equity_curve"]}
