"""Pronostico de una ventana horaria (p. ej. 21:00 -> 06:00 hora de El Salvador) en 1h.

Responde siempre la misma pregunta: "¿que va a hacer el oro entre ahora y el fin
de la ventana?". Metodo elegido (y por que no una regresion lineal pura): en la
pagina "Proyeccion por Regresion" el R² fuera de muestra del Ridge sale ~0 — la
direccion intradia casi no es predecible linealmente; lo que SI es estable es la
DISTRIBUCION (rango, colas, asimetria por horario). Por eso:

1. **Noches analogas completas (block bootstrap).** Por cada dia del historico se
   toma el mismo tramo horario (misma hora de inicio y duracion) como un camino
   entero de velas 1h. Remuestrear noches enteras conserva la autocorrelacion y el
   patron horario real (apertura de Londres, cierre de Asia...) — igual idea que el
   "Time Machine" de day-trader-skill, pero por bloques en vez de vela a vela.
2. **Escalado por volatilidad.** Cada camino se divide por la volatilidad que habia
   antes de esa noche y se multiplica por la actual: noches de 2025 y de hoy son
   comparables aunque el oro haya cambiado de nivel o de regimen.
3. **Peso por regimen (pocos parametros, fijados de antemano).** Solo 3 variables
   conocidas al inicio: momentum de 24h, distancia a la EMA de 120h y volatilidad
   relativa. Cada noche pesa segun su parecido (kernel gaussiano, ancho 1 fijo, sin
   optimizar). Ademas se filtra por estado de mercado: ventanas con el oro spot
   abierto vs fin de semana (PAXG cotiza 24/7 pero el spot cierra vie->dom).
4. **Encogimiento bayesiano hacia la tasa base.** Los pesos se mezclan con el
   promedio simple segun el tamaño de muestra efectivo (m = 20 noches de prior). Con
   pocas noches parecidas la respuesta se acerca a la tasa base; asi no se
   "sobreentrena" a un puñado de casos.
5. **Validacion walk-forward.** Cada noche del 40 % final se pronostica usando solo
   noches anteriores; se compara el Brier contra la tasa base (skill), la cobertura
   real de las bandas y una prueba binomial del acierto direccional.

Historico: Yahoo sirve velas 1h solo de los ultimos ~730 dias (~2 años, ~500 noches
habiles + ~200 de fin de semana). Error estandar de una probabilidad con n=500:
~±2 puntos — suficiente, y mas representativo del regimen actual que 2015-2020.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from scipy.stats import binom

LOCAL_TZ = "America/El_Salvador"
NY_TZ = "America/New_York"
FEATURE_LABELS = ("Momentum 24h", "Distancia EMA 120h", "Volatilidad relativa")
KERNEL_WIDTH = 1.0      # fijo a priori: no se optimiza (evita sobreajuste)
PRIOR_NIGHTS = 20.0     # fuerza del prior hacia la tasa base
MIN_TRAIN = 120         # noches minimas antes de empezar a validar
TEST_FRACTION = 0.4
REPLAYS = 5000
SEED = 19
BAND_Q = (0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95)
CALL_THRESHOLD = 0.55
TOUCH_LEVELS_Z = (0.5, 1.0, 1.5)  # niveles de validacion, en sigmas de la ventana


# ------------------------------------------------------------------ preparacion

def hourly_grid(df: pd.DataFrame) -> pd.DataFrame:
    """Velas 1h en una grilla horaria UTC completa (NaN donde falta la vela)."""
    d = df.copy()
    idx = pd.DatetimeIndex(d.index)
    d.index = (idx.tz_localize("UTC") if idx.tz is None else idx.tz_convert("UTC")).floor("h")
    d = d[~d.index.duplicated(keep="last")].sort_index()
    full = pd.date_range(d.index[0], d.index[-1], freq="h")
    return d.reindex(full)[["open", "high", "low", "close"]]


def grid_features(g: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    """Variables en cada hora T usando SOLO velas anteriores a T (shift 1)."""
    logc = np.log(g["close"])
    lr = logc.diff()
    sigma = lr.rolling(72, min_periods=48).std().shift(1)
    prev = logc.shift(1)
    z24 = (prev - logc.shift(25)) / (sigma * np.sqrt(24))
    ema = np.log(g["close"].ffill().ewm(span=120, adjust=False).mean()).shift(1)
    trend = (prev - ema) / (sigma * np.sqrt(24))
    volr = np.log(sigma / sigma.rolling(1440, min_periods=240).median())
    F = np.column_stack([z24, trend, volr]).astype(float)
    return np.clip(F, -4, 4), sigma.to_numpy(dtype=float)


def market_closed(times: pd.DatetimeIndex) -> np.ndarray:
    """True si el oro spot esta cerrado (vie 17:00 -> dom 18:00, hora de NY)."""
    ny = times.tz_convert(NY_TZ)
    wd, hr = ny.weekday, ny.hour
    return np.asarray((wd == 5) | ((wd == 4) & (hr >= 17)) | ((wd == 6) & (hr < 18)))


@dataclass
class Segments:
    anchors: pd.DatetimeIndex   # inicio de cada noche historica (UTC)
    close: np.ndarray           # (N, L) log(cierre / apertura del ancla)
    high: np.ndarray
    low: np.ndarray
    sigma: np.ndarray           # (N,) volatilidad horaria previa
    feats: np.ndarray           # (N, 3)
    closed: np.ndarray          # (N,) bool: mayoria de horas con el spot cerrado


def build_segments(g: pd.DataFrame, F: np.ndarray, sigma: np.ndarray, anchor_pos: np.ndarray, L: int) -> Segments:
    o = np.log(g["open"].to_numpy())
    c, h, lo = (np.log(g[k].to_numpy()) for k in ("close", "high", "low"))
    steps = anchor_pos[:, None] + np.arange(L)[None, :]
    C = c[steps] - o[anchor_pos][:, None]
    H = np.maximum.accumulate(h[steps] - o[anchor_pos][:, None], axis=1)
    Lw = np.minimum.accumulate(lo[steps] - o[anchor_pos][:, None], axis=1)
    closed_hours = market_closed(g.index)
    closed = closed_hours[steps].mean(axis=1) > 0.5
    ok = (
        np.isfinite(C).all(1) & np.isfinite(H).all(1) & np.isfinite(Lw).all(1)
        & np.isfinite(F[anchor_pos]).all(1) & np.isfinite(sigma[anchor_pos]) & (sigma[anchor_pos] > 0)
    )
    return Segments(
        anchors=g.index[anchor_pos][ok], close=C[ok], high=H[ok], low=Lw[ok],
        sigma=sigma[anchor_pos][ok], feats=F[anchor_pos][ok], closed=closed[ok],
    )


def analog_weights(F_hist: np.ndarray, f_now: np.ndarray) -> tuple[np.ndarray, float, float]:
    scale = F_hist.std(axis=0)
    scale[scale == 0] = 1.0
    d2 = (((F_hist - f_now) / scale) ** 2).sum(axis=1)
    w = np.exp(-d2 / (2 * KERNEL_WIDTH ** 2))
    if w.sum() <= 0:
        w = np.ones(len(F_hist))
    n_eff = float(w.sum() ** 2 / (w ** 2).sum())
    w = w / w.sum()
    beta = PRIOR_NIGHTS / (n_eff + PRIOR_NIGHTS)
    return (1 - beta) * w + beta / len(w), n_eff, beta


def wquantile(x: np.ndarray, w: np.ndarray, qs) -> np.ndarray:
    order = np.argsort(x)
    xs, ws = x[order], w[order]
    cw = (np.cumsum(ws) - 0.5 * ws) / ws.sum()
    return np.interp(qs, cw, xs)


# ------------------------------------------------------------------- validacion

def walk_forward(seg: Segments, L: int) -> dict:
    """Cada noche del tramo final se pronostica solo con noches previas que ya
    habian terminado (ancla + L horas <= ancla de la noche evaluada)."""
    n = len(seg.anchors)
    if n < MIN_TRAIN + 30:
        return {}
    z_end = seg.close[:, -1] / seg.sigma
    z_hi = seg.high[:, -1] / seg.sigma
    z_lo = seg.low[:, -1] / seg.sigma
    touch_lv = np.asarray(TOUCH_LEVELS_Z) * np.sqrt(L)
    t_ns = seg.anchors.as_unit("ns").asi8
    start = max(MIN_TRAIN, int(n * (1 - TEST_FRACTION)))
    rec, touch_rec = [], []
    for i in range(start, n):
        prior = np.flatnonzero((t_ns + L * 3_600_000_000_000 <= t_ns[i]) & (seg.closed == seg.closed[i]))
        if len(prior) < MIN_TRAIN // 2:
            continue
        w, _, _ = analog_weights(seg.feats[prior], seg.feats[i])
        z = z_end[prior]
        p_up = float(np.sum(w * (z > 0)))
        base = float(np.mean(z > 0))
        q = wquantile(z, w, (0.05, 0.10, 0.25, 0.75, 0.90, 0.95))
        # Probabilidad de tocar +/-k sigma: predicha (ponderada) vs ocurrida.
        pt_up = [float(np.sum(w * (z_hi[prior] >= lv))) for lv in touch_lv]
        pt_dn = [float(np.sum(w * (z_lo[prior] <= -lv))) for lv in touch_lv]
        hit_up = [float(z_hi[i] >= lv) for lv in touch_lv]
        hit_dn = [float(z_lo[i] <= -lv) for lv in touch_lv]
        rec.append((p_up, base, z_end[i] > 0, z_end[i], *q))
        touch_rec.append(pt_up + pt_dn + hit_up + hit_dn)
    if not rec:
        return {}
    R = np.array(rec, dtype=float)
    p, base, up, zi = R[:, 0], R[:, 1], R[:, 2].astype(bool), R[:, 3]
    q05, q10, q25, q75, q90, q95 = R[:, 4:].T
    brier_m = float(np.mean((p - up) ** 2))
    brier_b = float(np.mean((base - up) ** 2))
    calls = (p >= CALL_THRESHOLD) | (p <= 1 - CALL_THRESHOLD)
    hits = int(np.sum((p[calls] > 0.5) == up[calls]))
    n_calls = int(calls.sum())
    TR = np.array(touch_rec)
    k = len(TOUCH_LEVELS_Z)
    touch_cal = []
    for j, lz in enumerate(TOUCH_LEVELS_Z):
        touch_cal.append((f"+{lz:g}σ", float(TR[:, j].mean()), float(TR[:, 2 * k + j].mean())))
        touch_cal.append((f"-{lz:g}σ", float(TR[:, k + j].mean()), float(TR[:, 3 * k + j].mean())))
    return {
        "touch_calibration": touch_cal,
        "n_test": int(len(R)), "brier_model": brier_m, "brier_base": brier_b,
        "skill": 1 - brier_m / brier_b if brier_b > 0 else float("nan"),
        "cov50": float(np.mean((zi >= q25) & (zi <= q75))),
        "cov80": float(np.mean((zi >= q10) & (zi <= q90))),
        "cov90": float(np.mean((zi >= q05) & (zi <= q95))),
        "n_calls": n_calls, "hits": hits,
        "accuracy": hits / n_calls if n_calls else float("nan"),
        "p_value": float(binom.sf(hits - 1, n_calls, 0.5)) if n_calls else float("nan"),
        "test_from": pd.Timestamp(t_ns[start], tz="UTC"),
    }


# --------------------------------------------------------------------- pronostico

@dataclass
class WindowForecast:
    start_local: pd.Timestamp
    end_local: pd.Timestamp
    active: bool
    anchor_utc: pd.Timestamp
    anchor_open: float
    price_now: float
    sigma_now: float
    closed_market: bool
    step_times_utc: pd.DatetimeIndex     # cierre de cada vela proyectada
    bands: np.ndarray                    # (len(BAND_Q), L+1) precios, col 0 = ancla
    p_above_now: float                   # P(precio al final > precio actual)
    p_above_window_open: float | None    # si la ventana ya empezo
    window_open_price: float | None
    end_quantiles: dict
    touch_levels: list                   # [(nivel, P(toca))]
    range_median: float
    up_ext_median: float
    down_ext_median: float
    n_nights: int
    n_eff: float
    beta: float
    base_p_up: float
    feats_now: np.ndarray
    validation: dict = field(default_factory=dict)


def _window_bounds(t_local: pd.Timestamp, start_h: int, end_h: int) -> tuple[pd.Timestamp, pd.Timestamp, bool]:
    length = (end_h - start_h) % 24 or 24
    s_prev = t_local.normalize() + pd.Timedelta(hours=start_h)
    if s_prev > t_local:
        s_prev -= pd.Timedelta(days=1)
    if t_local < s_prev + pd.Timedelta(hours=length):
        return s_prev, s_prev + pd.Timedelta(hours=length), True
    s = s_prev + pd.Timedelta(days=1)
    return s, s + pd.Timedelta(hours=length), False


def _nice_step(x: float) -> float:
    for s in (1, 2, 2.5, 5, 10, 20, 25, 50, 100):
        if x <= s:
            return float(s)
    return 100.0 * np.ceil(x / 100)


def forecast_window(df_1h: pd.DataFrame, start_h: int = 21, end_h: int = 6,
                    replays: int = REPLAYS, seed: int = SEED) -> WindowForecast | None:
    g = hourly_grid(df_1h)
    F, sigma = grid_features(g)
    valid = np.flatnonzero(np.isfinite(g["close"].to_numpy()))
    if len(valid) < 24 * 200:
        return None
    pT = int(valid[-1])
    T = g.index[pT]
    t_local = T.tz_convert(LOCAL_TZ)
    S, E, active = _window_bounds(t_local, start_h, end_h)
    L = int(round((E - t_local) / pd.Timedelta(hours=1)))
    if L < 1 or not np.isfinite(F[pT]).all() or not np.isfinite(sigma[pT]):
        return None

    # ---- tramo vivo: mismo reloj (ancla T) en cada dia previo
    anchors = np.arange(pT - 24, -1, -24)[::-1]
    anchors = anchors[anchors + L <= pT]
    seg = build_segments(g, F, sigma, anchors, L)
    future_hours = pd.date_range(T, periods=L, freq="h")
    closed_now = bool(market_closed(future_hours).mean() > 0.5)
    keep = seg.closed == closed_now
    if keep.sum() < 60:
        return None
    C, H, Lo, sig, Fh = seg.close[keep], seg.high[keep], seg.low[keep], seg.sigma[keep], seg.feats[keep]
    w, n_eff, beta = analog_weights(Fh, F[pT])

    sigma_now = float(sigma[pT])
    anchor_open = float(g["open"].iloc[pT])
    price_now = float(g["close"].iloc[pT])
    rng = np.random.default_rng(seed)
    pick = rng.choice(len(C), size=replays, p=w)
    k = sigma_now / sig[pick]
    paths = anchor_open * np.exp(C[pick] * k[:, None])
    hi_max = anchor_open * np.exp(H[pick, -1] * k)
    lo_min = anchor_open * np.exp(Lo[pick, -1] * k)

    bands = np.empty((len(BAND_Q), L + 1))
    bands[:, 0] = anchor_open
    bands[:, 1:] = np.quantile(paths, BAND_Q, axis=0)
    end = paths[:, -1]

    window_open_price = None
    p_above_open = None
    if active:
        s_utc = S.tz_convert("UTC")
        if s_utc in g.index and np.isfinite(g.at[s_utc, "open"]):
            window_open_price = float(g.at[s_utc, "open"])
            p_above_open = float(np.mean(end > window_open_price))

    # Escalera de "probabilidad de tocar" alrededor del precio actual.
    rng_med = float(np.median(hi_max - lo_min))
    step = _nice_step(rng_med / 4)
    base_lvl = np.round(price_now / step) * step
    levels = []
    for j in range(1, 6):
        up_l, dn_l = base_lvl + j * step, base_lvl - j * step
        if up_l > price_now:
            levels.append((float(up_l), float(np.mean(hi_max >= up_l))))
        if dn_l < price_now:
            levels.append((float(dn_l), float(np.mean(lo_min <= dn_l))))
    levels.sort(key=lambda x: -x[0])

    validation = {}
    # Validacion de la pregunta "nucleo": desde el inicio de la ventana hasta su fin.
    length = (end_h - start_h) % 24 or 24
    p_start = pT + int(round((S.tz_convert("UTC") - T) / pd.Timedelta(hours=1)))
    va = np.arange(p_start, -1, -24)[::-1]
    va = va[va + length <= pT]
    if len(va) > MIN_TRAIN:
        validation = walk_forward(build_segments(g, F, sigma, va, length), length)

    base_end = anchor_open * np.exp(C[:, -1] * sigma_now / sig)
    base_p = float(np.mean(base_end > price_now))
    return WindowForecast(
        start_local=S, end_local=E, active=active, anchor_utc=T, anchor_open=anchor_open,
        price_now=price_now, sigma_now=sigma_now, closed_market=closed_now,
        step_times_utc=pd.date_range(T, periods=L + 1, freq="h"),
        bands=bands, p_above_now=float(np.mean(end > price_now)),
        p_above_window_open=p_above_open, window_open_price=window_open_price,
        end_quantiles={q: float(v) for q, v in zip(BAND_Q, np.quantile(end, BAND_Q))},
        touch_levels=levels, range_median=rng_med,
        up_ext_median=float(np.median(hi_max - price_now)),
        down_ext_median=float(np.median(price_now - lo_min)),
        n_nights=int(len(C)), n_eff=n_eff, beta=beta, base_p_up=base_p,
        feats_now=F[pT], validation=validation,
    )


def verdict(p_up: float) -> tuple[str, str]:
    if p_up >= 0.60:
        return "ALCISTA", "bull"
    if p_up >= CALL_THRESHOLD:
        return "LEVE SESGO ALCISTA", "bull"
    if p_up <= 0.40:
        return "BAJISTA", "bear"
    if p_up <= 1 - CALL_THRESHOLD:
        return "LEVE SESGO BAJISTA", "bear"
    return "NEUTRAL", "warning"
