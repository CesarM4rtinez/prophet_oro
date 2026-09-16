"""Scorecard tecnico multi-indicador (scalping), patrones de vela y proyeccion Monte Carlo (GBM)."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .smc_zones import atr

WEIGHTS = {"ema": 0.30, "rsi": 0.15, "macd": 0.25, "bollinger": 0.15, "stoch": 0.15}


def _ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def _rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain, loss = delta.clip(lower=0), -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).fillna(50.0)


def _macd(close: pd.Series):
    macd_line = _ema(close, 12) - _ema(close, 26)
    return macd_line, _ema(macd_line, 9)


def _bollinger(close: pd.Series, period: int = 20, n_std: float = 2.0):
    mid = close.rolling(period).mean()
    std = close.rolling(period).std()
    return mid, mid + n_std * std, mid - n_std * std


def _stochastic(df: pd.DataFrame, k_period: int = 14, d_period: int = 3):
    low_min = df["low"].rolling(k_period).min()
    high_max = df["high"].rolling(k_period).max()
    k = ((df["close"] - low_min) / (high_max - low_min).replace(0, np.nan) * 100).fillna(50.0)
    return k, k.rolling(d_period).mean()


def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["ema9"], out["ema21"], out["ema50"] = _ema(out["close"], 9), _ema(out["close"], 21), _ema(out["close"], 50)
    out["rsi14"] = _rsi(out["close"])
    out["macd"], out["macd_signal"] = _macd(out["close"])
    out["bb_mid"], out["bb_upper"], out["bb_lower"] = _bollinger(out["close"])
    out["atr14"] = atr(out)
    out["stoch_k"], out["stoch_d"] = _stochastic(out)
    out["rel_volume"] = out["volume"] / out["volume"].rolling(20).mean().replace(0, np.nan)
    return out


def logistic(x: float, k: float = 4.0) -> float:
    return 1 / (1 + np.exp(-k * x))


def score_last(df_ind: pd.DataFrame, weights: dict = WEIGHTS) -> dict:
    row = df_ind.iloc[-1]
    atr_ref = row["atr14"] if pd.notna(row["atr14"]) and row["atr14"] > 0 else row["close"] * 0.01

    ema_component = float(np.tanh((row["ema9"] - row["ema50"]) / atr_ref))
    rsi_component = float((row["rsi14"] - 50) / 50) if pd.notna(row["rsi14"]) else 0.0
    macd_component = float(np.tanh((row["macd"] - row["macd_signal"]) / atr_ref)) if pd.notna(row["macd"]) else 0.0
    band_width = (row["bb_upper"] - row["bb_mid"]) if pd.notna(row["bb_upper"]) else atr_ref
    band_width = band_width or atr_ref
    bollinger_component = float(np.clip((row["close"] - row["bb_mid"]) / band_width, -1, 1)) if pd.notna(row["bb_mid"]) else 0.0
    stoch_component = float((row["stoch_k"] - 50) / 50) if pd.notna(row["stoch_k"]) else 0.0

    raw_score = (
        weights["ema"] * ema_component
        + weights["rsi"] * rsi_component
        + weights["macd"] * macd_component
        + weights["bollinger"] * bollinger_component
        + weights["stoch"] * stoch_component
    )

    rel_vol = float(row["rel_volume"]) if pd.notna(row["rel_volume"]) else 1.0
    volume_multiplier = float(np.clip(rel_vol, 0.5, 2.0))
    score = float(np.clip(raw_score * volume_multiplier, -1, 1))
    buy_probability = logistic(score) * 100

    return {
        "score": score,
        "buy_probability": buy_probability,
        "sell_probability": 100 - buy_probability,
        "components": {
            "EMA (tendencia)": ema_component,
            "RSI": rsi_component,
            "MACD": macd_component,
            "Bollinger": bollinger_component,
            "Estocastico": stoch_component,
        },
        "rel_volume": rel_vol,
        "atr14": float(row["atr14"]) if pd.notna(row["atr14"]) else None,
    }


def risk_levels(entry: float, atr14: float | None, direction: str = "buy", sl_atr_mult: float = 1.5, rr_levels=(1, 2, 3)) -> dict:
    atr14 = atr14 or entry * 0.01
    risk = sl_atr_mult * atr14
    if direction == "buy":
        stoploss = entry - risk
        targets = [entry + rr * risk for rr in rr_levels]
    else:
        stoploss = entry + risk
        targets = [entry - rr * risk for rr in rr_levels]
    return {"entry": entry, "stoploss": stoploss, "targets": targets, "risk": risk}


def detect_candle_patterns(df: pd.DataFrame, lookback: int = 5) -> list[dict]:
    patterns = []
    n = len(df)
    for i in range(max(1, n - lookback), n):
        o, h, l, c = df["open"].iloc[i], df["high"].iloc[i], df["low"].iloc[i], df["close"].iloc[i]
        po, pc = df["open"].iloc[i - 1], df["close"].iloc[i - 1]
        body = abs(c - o)
        range_ = (h - l) or 1e-9
        upper_wick, lower_wick = h - max(o, c), min(o, c) - l

        if body <= 0.1 * range_:
            patterns.append({"idx": i, "name": "Doji"})
        elif c > o and po > pc and c >= po and o <= pc:
            patterns.append({"idx": i, "name": "Envolvente alcista"})
        elif c < o and pc > po and o >= pc and c <= po:
            patterns.append({"idx": i, "name": "Envolvente bajista"})
        elif lower_wick >= 2 * body and upper_wick <= 0.3 * body + 1e-9:
            patterns.append({"idx": i, "name": "Martillo"})
        elif upper_wick >= 2 * body and lower_wick <= 0.3 * body + 1e-9:
            patterns.append({"idx": i, "name": "Estrella fugaz"})
    return patterns


def monte_carlo_gbm(close: np.ndarray, n_steps: int = 30, n_paths: int = 500, seed: int | None = 42) -> dict:
    log_returns = np.diff(np.log(close))
    mu, sigma = float(np.mean(log_returns)), float(np.std(log_returns))
    rng = np.random.default_rng(seed)
    s0 = float(close[-1])
    shocks = rng.normal(size=(n_paths, n_steps))
    drift = mu - 0.5 * sigma**2
    log_paths = np.cumsum(drift + sigma * shocks, axis=1)
    paths = np.hstack([np.full((n_paths, 1), s0), s0 * np.exp(log_paths)])

    return {
        "median": np.median(paths, axis=0),
        "bands": {
            "95%": (np.percentile(paths, 2.5, axis=0), np.percentile(paths, 97.5, axis=0)),
            "80%": (np.percentile(paths, 10, axis=0), np.percentile(paths, 90, axis=0)),
            "50%": (np.percentile(paths, 25, axis=0), np.percentile(paths, 75, axis=0)),
        },
    }
