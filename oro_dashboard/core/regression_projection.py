"""Proyeccion probabilistica por regresion para 5m / 15m / 1h.

Combina tres estimadores, tomados de las dos infografias que pidio el usuario
(10 modelos de regresion + 10 formulas de probabilidad) y del "Time Machine" de
github.com/Jakeschincariol/day-trader-skill:

1. **Ridge (L2) multi-horizonte** — una regresion lineal multiple por cada vela
   futura h = 1..H. Variables: momentum (retornos 1/3/6/12 velas), un termino
   polinomico (momentum^2), distancia a EMA20/EMA50 en ATRs, volatilidad, RSI,
   posicion en el rango de 20 velas y hora del dia (sin/cos, el componente de
   "series de tiempo"). El objetivo es el retorno logaritmico a h velas
   normalizado por la volatilidad (heterocedasticidad). La lambda se elige en
   validacion walk-forward.
   Las bandas 5-25-50-75-95 % salen de los cuantiles de los residuos fuera de
   muestra (regresion cuantilica conformal: misma idea que la regresion
   cuantilica, pero sin resolver un LP por cada cuantil y horizonte).
2. **Regresion logistica (L2, IRLS)** — P(cierre en t+H > cierre en t).
3. **Monte Carlo "Time Machine"** — 5 000 replays de las proximas H velas
   remuestreando velas reales del mismo horario (+/- 2 velas) y escalandolas al
   precio actual; chequea stop antes que target dentro de una vela (conservador),
   igual que timemachine.py.

Validacion honesta: los modelos se ajustan con el 80 % inicial y se miden en el
20 % final (con un hueco de H velas para no filtrar el futuro). Sobre ese tramo
se calcula la precision direccional, una prueba binomial contra 50 % (formula
10 de la infografia de probabilidad), la probabilidad condicional / Bayes
P(sube | el modelo dice sube) y la cobertura real de la banda del 90 %.

Nada de esto es una promesa: es una estimacion estadistica sobre datos
pasados de PAXG-USD (proxy del spot XAU/USD).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from scipy.stats import binom

# Horizonte de proyeccion por temporalidad (en velas) y duracion de cada vela.
HORIZONS = {"5m": 12, "15m": 16, "1h": 24}  # 1 h, 4 h, 1 dia
BAR_MINUTES = {"5m": 5, "15m": 15, "1h": 60}
# Ventana maxima de entrenamiento (velas mas recientes) y del pool de Monte Carlo.
TRAIN_BARS = 6000
MC_POOL_DAYS = {"5m": 60, "15m": 60, "1h": 180}
MC_REPLAYS = 5000
MC_SEED = 19  # mismo seed por defecto que timemachine.py: resultados repetibles
MC_WINDOW = 2
QUANTILES = (0.05, 0.25, 0.5, 0.75, 0.95)
RIDGE_LAMBDAS = (0.3, 1.0, 3.0, 10.0, 30.0, 100.0, 300.0, 1000.0, 3000.0)
STOP_ATR = 1.0
TARGET_ATR = 1.5

FEATURE_NAMES = [
    "Ret 1 vela", "Ret 3 velas", "Ret 6 velas", "Ret 12 velas", "Momentum²",
    "Dist. EMA20 (ATR)", "Dist. EMA50 (ATR)", "Volatilidad", "RSI 14",
    "Posicion rango 20", "Hora (sin)", "Hora (cos)",
]


# --------------------------------------------------------------------- features

def _rsi(close: pd.Series, n: int = 14) -> pd.Series:
    delta = close.diff()
    up = delta.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    down = (-delta.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    rs = up / down.replace(0, np.nan)
    return 100 - 100 / (1 + rs)


def _atr(df: pd.DataFrame, n: int = 14) -> pd.Series:
    prev = df["close"].shift(1)
    tr = pd.concat(
        [df["high"] - df["low"], (df["high"] - prev).abs(), (df["low"] - prev).abs()], axis=1
    ).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()


def build_features(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series, pd.Series]:
    """Matriz X (solo usa informacion hasta t), volatilidad por vela y ATR."""
    close = df["close"].astype(float)
    logc = np.log(close)
    r1 = logc.diff()
    vol = r1.rolling(50, min_periods=20).std()
    atr = _atr(df)
    ema20 = close.ewm(span=20, adjust=False).mean()
    ema50 = close.ewm(span=50, adjust=False).mean()
    hi20 = df["high"].rolling(20).max()
    lo20 = df["low"].rolling(20).min()
    rng = (hi20 - lo20).replace(0, np.nan)
    idx = pd.DatetimeIndex(df.index)
    minutes = idx.hour * 60 + idx.minute
    angle = 2 * np.pi * np.asarray(minutes) / 1440.0
    # Retornos en unidades de volatilidad: hace comparables velas tranquilas y volatiles.
    v = vol.replace(0, np.nan)
    m12 = (logc - logc.shift(12)) / (v * np.sqrt(12))
    X = pd.DataFrame(
        {
            "r1": r1 / v,
            "r3": (logc - logc.shift(3)) / (v * np.sqrt(3)),
            "r6": (logc - logc.shift(6)) / (v * np.sqrt(6)),
            "r12": m12,
            "mom2": np.sign(m12) * m12 ** 2,
            "ema20": (close - ema20) / atr,
            "ema50": (close - ema50) / atr,
            "vol": np.log(v / v.rolling(500, min_periods=50).median()),
            "rsi": (_rsi(close) - 50) / 50,
            "pos20": (close - lo20) / rng - 0.5,
            "hsin": np.sin(angle),
            "hcos": np.cos(angle),
        },
        index=df.index,
    )
    return X, vol, atr


def _targets(close: pd.Series, vol: pd.Series, horizon: int) -> np.ndarray:
    """Matriz (n, H): retorno log a h velas, normalizado por vol_t * sqrt(h)."""
    logc = np.log(close.to_numpy(dtype=float))
    n = len(logc)
    Y = np.full((n, horizon), np.nan)
    v = vol.to_numpy(dtype=float)
    for h in range(1, horizon + 1):
        Y[: n - h, h - 1] = (logc[h:] - logc[: n - h]) / (v[: n - h] * np.sqrt(h))
    return Y


# ----------------------------------------------------------------------- models

def ridge_fit(X: np.ndarray, Y: np.ndarray, lam: float) -> np.ndarray:
    """Ridge en forma cerrada para varias salidas a la vez. X ya estandarizada,
    con columna de unos al final (el intercepto no se penaliza)."""
    p = X.shape[1]
    penalty = lam * np.eye(p)
    penalty[-1, -1] = 0.0
    return np.linalg.solve(X.T @ X + penalty, X.T @ Y)


def logistic_fit(X: np.ndarray, y: np.ndarray, lam: float = 1.0, iters: int = 25) -> np.ndarray:
    """Regresion logistica L2 por Newton-Raphson (IRLS). P(Y=1) = 1 / (1 + e^-(Xb))."""
    p = X.shape[1]
    beta = np.zeros(p)
    penalty = lam * np.eye(p)
    penalty[-1, -1] = 0.0
    for _ in range(iters):
        z = np.clip(X @ beta, -30, 30)
        prob = 1 / (1 + np.exp(-z))
        w = prob * (1 - prob)
        grad = X.T @ (prob - y) + penalty @ beta
        hess = (X * w[:, None]).T @ X + penalty + 1e-9 * np.eye(p)
        step = np.linalg.solve(hess, grad)
        beta -= step
        if np.max(np.abs(step)) < 1e-7:
            break
    return beta


def _sigmoid(z: np.ndarray) -> np.ndarray:
    return 1 / (1 + np.exp(-np.clip(z, -30, 30)))


def _standardize(train: np.ndarray, *others: np.ndarray):
    mu = train.mean(axis=0)
    sd = train.std(axis=0)
    sd[sd == 0] = 1.0

    def tr(a):
        return np.column_stack([(a - mu) / sd, np.ones(len(a))])

    return (tr(train), *[tr(o) for o in others])


# ------------------------------------------------------------------ Monte Carlo

def _slot_of(index: pd.DatetimeIndex, bar_minutes: int) -> np.ndarray:
    return ((index.hour * 60 + index.minute) // bar_minutes).to_numpy()


def monte_carlo(
    df: pd.DataFrame, label: str, horizon: int, atr_now: float,
    replays: int = MC_REPLAYS, seed: int = MC_SEED, window: int = MC_WINDOW,
) -> dict:
    """Replays al estilo trader-timemachine: cada vela futura se toma al azar de las
    velas pasadas del mismo horario (+/- `window` velas), como razones
    (o, h, l, c) / cierre previo, y se escala al precio actual."""
    bar_min = BAR_MINUTES[label]
    slots_per_day = 1440 // bar_min
    cutoff = df.index[-1] - pd.Timedelta(days=MC_POOL_DAYS[label])
    hist = df[df.index >= cutoff]
    prev_close = hist["close"].shift(1)
    # Solo velas consecutivas (sin huecos de mercado cerrado / datos faltantes).
    gap_ok = hist.index.to_series().diff() == pd.Timedelta(minutes=bar_min)
    ratios = pd.DataFrame(
        {k: hist[k] / prev_close for k in ("open", "high", "low", "close")}, index=hist.index
    )[gap_ok].dropna()
    if len(ratios) < 200:
        return {}
    slot = _slot_of(ratios.index, bar_min)
    order = np.argsort(slot, kind="stable")
    R = ratios.to_numpy()[order]
    slot_sorted = slot[order]
    counts = np.bincount(slot_sorted, minlength=slots_per_day)
    starts = np.concatenate([[0], np.cumsum(counts)[:-1]])
    # Horarios sin muestras (p. ej. pausa diaria de un mercado): se usa todo el pool.
    empty = counts == 0

    rng = np.random.default_rng(seed)
    entry = float(df["close"].iloc[-1])
    next_slot0 = (_slot_of(pd.DatetimeIndex([df.index[-1]]), bar_min)[0] + 1) % slots_per_day

    long_stop, long_tgt = entry - STOP_ATR * atr_now, entry + TARGET_ATR * atr_now
    short_stop, short_tgt = entry + STOP_ATR * atr_now, entry - TARGET_ATR * atr_now
    long_out = np.zeros(replays, dtype=np.int8)   # 0 = ninguno, 1 = target, -1 = stop
    short_out = np.zeros(replays, dtype=np.int8)

    price = np.full(replays, entry)
    paths = np.empty((replays, horizon + 1))
    paths[:, 0] = entry
    for j in range(horizon):
        s = (next_slot0 + j + rng.integers(-window, window + 1, size=replays)) % slots_per_day
        pick = np.where(
            empty[s],
            rng.integers(0, len(R), size=replays),
            starts[s] + (rng.random(replays) * np.maximum(counts[s], 1)).astype(int),
        )
        o, h, lo, c = R[pick].T
        hi_p, lo_p = price * h, price * lo
        # Stop primero si una misma vela toca ambos (criterio conservador de timemachine.py).
        open_l = long_out == 0
        long_out[open_l & (lo_p <= long_stop)] = -1
        long_out[(long_out == 0) & open_l & (hi_p >= long_tgt)] = 1
        open_s = short_out == 0
        short_out[open_s & (hi_p >= short_stop)] = -1
        short_out[(short_out == 0) & open_s & (lo_p <= short_tgt)] = 1
        price = price * c
        paths[:, j + 1] = price

    bands = np.quantile(paths, QUANTILES, axis=0)
    r_target = TARGET_ATR / STOP_ATR

    def plan(out, final_ret_sign):
        p_t, p_s = float(np.mean(out == 1)), float(np.mean(out == -1))
        neither = out == 0
        # R al cierre del horizonte para los que no tocaron ningun lado.
        r_close = final_ret_sign * (price - entry) / (STOP_ATR * atr_now)
        Rs = np.where(out == 1, r_target, np.where(out == -1, -1.0, r_close))
        decided = p_t + p_s
        win_share = p_t / decided if decided > 0 else float("nan")
        return {
            "p_target": p_t, "p_stop": p_s, "p_neither": float(np.mean(neither)),
            "avg_R": float(np.mean(Rs)), "win_share": win_share,
            "breakeven": 1 / (1 + r_target), "verdict": _verdict(win_share, 1 / (1 + r_target)),
        }

    return {
        "bands": bands, "p_up": float(np.mean(price > entry)),
        "median_end": float(np.median(price)), "pool_bars": int(len(R)),
        "long": plan(long_out, 1.0), "short": plan(short_out, -1.0),
        "long_levels": (long_stop, long_tgt), "short_levels": (short_stop, short_tgt),
        "replays": replays, "seed": seed,
    }


def _verdict(win_share: float, breakeven: float) -> str:
    """Misma regla que timemachine.py: compara la proporcion de replays que tocan
    el target primero (entre los que tocan algun lado) con el break-even 1/(1+R)."""
    if not np.isfinite(win_share):
        return "Sin decision: ningun replay toco stop ni target"
    gap = (win_share - breakeven) * 100
    if abs(gap) < 5:
        return "Cerca del break-even"
    side = "el target" if gap > 0 else "el stop"
    return ("Fuertemente hacia " if abs(gap) >= 15 else "Se inclina hacia ") + side


# ------------------------------------------------------------------- pipeline

@dataclass
class Projection:
    label: str
    horizon: int
    bar_minutes: int
    last_time: pd.Timestamp
    last_close: float
    atr: float
    future_index: pd.DatetimeIndex
    reg_bands: np.ndarray           # (5, H+1) precios para QUANTILES, incluye t0
    reg_p_up: float                 # P(sube a t+H) desde la regresion + residuos
    logit_p_up: float               # P(sube a t+H) desde la logistica
    mc: dict
    consensus_p_up: float
    metrics: dict = field(default_factory=dict)
    coefs: pd.Series | None = None
    n_train: int = 0


def project(df: pd.DataFrame, label: str) -> Projection | None:
    horizon = HORIZONS[label]
    df = df.dropna().tail(TRAIN_BARS + 600)
    if len(df) < 400:
        return None
    X_df, vol, atr = build_features(df)
    Y = _targets(df["close"], vol, horizon)
    X = X_df.to_numpy(dtype=float)

    valid_x = np.isfinite(X).all(axis=1) & np.isfinite(vol.to_numpy())
    labeled = valid_x & np.isfinite(Y).all(axis=1)
    rows = np.flatnonzero(labeled)
    if len(rows) < 300 or not valid_x[-1]:
        return None

    # ---- walk-forward: 80 % entrena, hueco de H velas, 20 % prueba
    split = int(len(rows) * 0.8)
    tr_rows = rows[: max(split - horizon, 50)]
    te_rows = rows[split:]
    Xtr, Xte = _standardize(X[tr_rows], X[te_rows])
    Ytr, Yte = Y[tr_rows], Y[te_rows]

    best = None
    for lam in RIDGE_LAMBDAS:
        B = ridge_fit(Xtr, Ytr, lam)
        mse = float(np.mean((Xte @ B - Yte) ** 2))
        if best is None or mse < best[0]:
            best = (mse, lam, B)
    _, lam, B_val = best
    pred_te = Xte @ B_val
    resid = Yte - pred_te  # (n_te, H) en unidades de volatilidad
    resid_q = np.quantile(resid, QUANTILES, axis=0)  # (5, H)

    # Metricas fuera de muestra al horizonte H
    yH, pH = Yte[:, -1], pred_te[:, -1]
    ss_res = float(np.sum((yH - pH) ** 2))
    ss_tot = float(np.sum((yH - yH.mean()) ** 2))
    r2_oos = 1 - ss_res / ss_tot if ss_tot > 0 else float("nan")
    # Cobertura honesta de la banda 90 %: cuantiles calibrados con la 1.a mitad
    # del tramo de prueba y medidos en la 2.a mitad (que no vieron).
    half = len(yH) // 2
    cal_q = np.quantile(resid[:half, -1], (0.05, 0.95))
    ev_y, ev_p = yH[half:], pH[half:]
    coverage = float(np.mean((ev_y >= ev_p + cal_q[0]) & (ev_y <= ev_p + cal_q[1])))

    ytr_bin = (Ytr[:, -1] > 0).astype(float)
    beta_val = logistic_fit(Xtr, ytr_bin)
    p_logit_te = _sigmoid(Xte @ beta_val)
    up_te = yH > 0
    brier = float(np.mean((p_logit_te - up_te) ** 2))

    # Precision direccional con muestras NO solapadas (cada H velas) -> prueba binomial.
    step_idx = np.arange(0, len(yH), horizon)
    p_ens_te = 0.5 * (p_logit_te + (pH > 0))
    calls_up = p_ens_te[step_idx] > 0.5
    hits = int(np.sum(calls_up == up_te[step_idx]))
    n_ind = int(len(step_idx))
    p_value = float(binom.sf(hits - 1, n_ind, 0.5)) if n_ind else float("nan")
    said_up = calls_up.sum()
    p_up_given_said_up = float(np.mean(up_te[step_idx][calls_up])) if said_up else float("nan")
    p_down_given_said_down = (
        float(np.mean(~up_te[step_idx][~calls_up])) if (n_ind - said_up) else float("nan")
    )
    base_rate_up = float(np.mean(up_te[step_idx])) if n_ind else float("nan")

    # ---- reajuste con todos los datos etiquetados para la proyeccion en vivo
    Xall, Xnow = _standardize(X[rows], X[[-1]])
    B = ridge_fit(Xall, Y[rows], lam)
    beta = logistic_fit(Xall, (Y[rows, -1] > 0).astype(float))
    z_hat = (Xnow @ B)[0]  # (H,)
    logit_p = float(_sigmoid(Xnow @ beta)[0])

    vol_now = float(vol.iloc[-1])
    last_close = float(df["close"].iloc[-1])
    sqrt_h = np.sqrt(np.arange(1, horizon + 1))
    bands = np.empty((len(QUANTILES), horizon + 1))
    bands[:, 0] = last_close
    for qi in range(len(QUANTILES)):
        bands[qi, 1:] = last_close * np.exp((z_hat + resid_q[qi]) * vol_now * sqrt_h)
    # P(sube) desde la distribucion empirica de residuos: P(z_hat + e > 0)
    reg_p_up = float(np.mean(resid[:, -1] > -z_hat[-1]))

    atr_now = float(atr.iloc[-1])
    mc = monte_carlo(df, label, horizon, atr_now)
    probs = [reg_p_up, logit_p] + ([mc["p_up"]] if mc else [])
    consensus = float(np.mean(probs))

    freq = pd.Timedelta(minutes=BAR_MINUTES[label])
    future_index = pd.DatetimeIndex([df.index[-1] + freq * k for k in range(horizon + 1)])

    coefs = pd.Series(B[:-1, -1], index=FEATURE_NAMES).sort_values(key=np.abs, ascending=False)
    return Projection(
        label=label, horizon=horizon, bar_minutes=BAR_MINUTES[label],
        last_time=df.index[-1], last_close=last_close, atr=atr_now,
        future_index=future_index, reg_bands=bands, reg_p_up=reg_p_up,
        logit_p_up=logit_p, mc=mc, consensus_p_up=consensus,
        metrics={
            "lambda": lam, "r2_oos": r2_oos, "coverage90": coverage, "brier": brier,
            "hits": hits, "n_independent": n_ind,
            "accuracy": hits / n_ind if n_ind else float("nan"), "p_value": p_value,
            "p_up_given_said_up": p_up_given_said_up,
            "p_down_given_said_down": p_down_given_said_down,
            "base_rate_up": base_rate_up, "n_test": int(len(te_rows)),
        },
        coefs=coefs, n_train=int(len(rows)),
    )


def signal_label(p_up: float, threshold: float = 0.55) -> tuple[str, str]:
    if p_up >= threshold:
        return "ALCISTA", "bull"
    if p_up <= 1 - threshold:
        return "BAJISTA", "bear"
    return "NEUTRAL", "warning"
