"""Motor de niveles diarios congelados para XAU/USD."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import time
from zoneinfo import ZoneInfo

import pandas as pd


# TradingView/ZoneInfo no reconoce America/NYCK. El horario solicitado coincide
# con El Salvador, que no aplica cambios estacionales de hora.
LOCAL_TZ = ZoneInfo("America/El_Salvador")


@dataclass(frozen=True)
class DailyLevelResult:
    data: pd.DataFrame
    active_date: str | None
    active_levels: dict[str, float] | None
    warning: str | None
    bias: str
    bull_signal: bool
    bear_signal: bool


def _utc_index(df: pd.DataFrame) -> pd.DataFrame:
    result = df.copy()
    index = pd.to_datetime(result.index)
    if index.tz is None:
        index = index.tz_localize("UTC")
    else:
        index = index.tz_convert("UTC")
    result.index = index
    return result.sort_index()


def _anchor_row(day: pd.DataFrame, anchor: time) -> pd.Series | None:
    matches = day[
        (day["local_time"].dt.hour == anchor.hour)
        & (day["local_time"].dt.minute == anchor.minute)
    ]
    return matches.iloc[0] if not matches.empty else None


def _format_missing(missing: list[str]) -> str:
    return "Faltan velas ancla: " + ", ".join(missing)


def calculate_daily_levels(
    df: pd.DataFrame,
    *,
    third_hour: int = 16,
    third_minute: int = 0,
    third_mode: str = "close",
    require_retest: bool = True,
    retest_bars_limit: int = 12,
) -> DailyLevelResult:
    """Calcula niveles congelados y señales sobre velas M5 cerradas.

    ``third_mode="close"`` busca la vela que abre cinco minutos antes de la
    hora configurada; ``third_mode="open"`` busca la vela que abre exactamente
    a esa hora. El índice de entrada se interpreta como apertura de vela.
    """
    required = {"open", "high", "low", "close"}
    missing_columns = required.difference(df.columns)
    if missing_columns:
        raise ValueError(f"Faltan columnas OHLC: {', '.join(sorted(missing_columns))}")
    if third_mode not in {"open", "close"}:
        raise ValueError("third_mode debe ser 'open' o 'close'")
    if retest_bars_limit < 1:
        raise ValueError("retest_bars_limit debe ser positivo")

    work = _utc_index(df[list(required)].dropna())
    if work.empty:
        return DailyLevelResult(work, None, None, "No hay datos M5.", "SIN NIVELES", False, False)

    now_utc = pd.Timestamp.now(tz="UTC")
    # yfinance puede devolver la vela en formación. Solo se conserva una vela
    # cuyo cierre ya ocurrió.
    work = work[work.index + pd.Timedelta(minutes=5) <= now_utc].copy()
    if work.empty:
        return DailyLevelResult(work, None, None, "No hay velas M5 cerradas.", "SIN NIVELES", False, False)

    work["local_time"] = work.index.tz_convert(LOCAL_TZ)
    work["local_date"] = work["local_time"].dt.date
    work["line_h07"] = float("nan")
    work["line_h1130"] = float("nan")
    work["line_l16"] = float("nan")
    work["bias"] = "SIN NIVELES"
    work["bull_signal"] = False
    work["bear_signal"] = False

    day_data = {date: group for date, group in work.groupby("local_date", sort=True)}
    anchor_sets: dict[object, dict[str, float] | None] = {}
    missing_by_day: dict[object, list[str]] = {}
    third_open = time(third_hour, third_minute)
    third_close_anchor = (
        time(third_hour, third_minute - 5)
        if third_minute >= 5
        else time((third_hour - 1) % 24, third_minute + 55)
    )

    for date, day in day_data.items():
        h07 = _anchor_row(day, time(7, 0))
        h1130 = _anchor_row(day, time(11, 30))
        third = _anchor_row(day, third_open if third_mode == "open" else third_close_anchor)
        missing = [
            label
            for label, row in (("H07", h07), ("H1130", h1130), ("L16", third))
            if row is None
        ]
        missing_by_day[date] = missing
        anchor_sets[date] = (
            None
            if missing
            else {"H07": float(h07["high"]), "H1130": float(h1130["high"]), "L16": float(third["low"])}
        )

    dates = sorted(day_data)
    last_valid: dict[str, float] | None = None
    latest_warning: str | None = None
    active_date: str | None = None
    active_levels: dict[str, float] | None = None
    bull_signal = False
    bear_signal = False

    for date in dates:
        day = day_data[date]
        # El conjunto activo del día D procede del día de mercado anterior
        # disponible. Nunca se activa en el mismo día de sus anclas.
        prior_dates = [candidate for candidate in dates if candidate < date]
        reference_date = prior_dates[-1] if prior_dates else None
        if reference_date is not None:
            if anchor_sets[reference_date] is not None:
                last_valid = anchor_sets[reference_date]
                active_date = str(reference_date)
                active_levels = last_valid
                latest_warning = None
            elif missing_by_day[reference_date]:
                latest_warning = (
                    f"{reference_date}: {_format_missing(missing_by_day[reference_date])}. "
                    "Se conserva el último conjunto válido."
                )

        if active_levels is None:
            continue

        mask = work["local_date"] == date
        work.loc[mask, "line_h07"] = active_levels["H07"]
        work.loc[mask, "line_h1130"] = active_levels["H1130"]
        work.loc[mask, "line_l16"] = active_levels["L16"]

        upper = max(active_levels["H07"], active_levels["H1130"])
        lower = active_levels["L16"]
        pending_bull = False
        pending_bear = False
        bull_wait = 0
        bear_wait = 0
        bull_done = False
        bear_done = False

        for timestamp, row in day.iterrows():
            close = float(row["close"])
            high = float(row["high"])
            low = float(row["low"])
            above = close > upper
            below = close < lower
            if above:
                work.at[timestamp, "bias"] = "ALCISTA"
            elif below:
                work.at[timestamp, "bias"] = "BAJISTA"
            else:
                work.at[timestamp, "bias"] = "NEUTRAL"

            if require_retest:
                if above and not bull_done and not pending_bull:
                    pending_bull = True
                    bull_wait = 0
                    pending_bear = False
                if below and not bear_done and not pending_bear:
                    pending_bear = True
                    bear_wait = 0
                    pending_bull = False

                if pending_bull:
                    bull_wait += 1
                    if bull_wait > 1 and low <= upper and close > upper:
                        work.at[timestamp, "bull_signal"] = True
                        bull_done = True
                        bull_signal = True
                        pending_bull = False
                    elif bull_wait >= retest_bars_limit or below:
                        pending_bull = False

                if pending_bear:
                    bear_wait += 1
                    if bear_wait > 1 and high >= lower and close < lower:
                        work.at[timestamp, "bear_signal"] = True
                        bear_done = True
                        bear_signal = True
                        pending_bear = False
                    elif bear_wait >= retest_bars_limit or above:
                        pending_bear = False
            else:
                if above and not bull_done:
                    work.at[timestamp, "bull_signal"] = True
                    bull_done = True
                    bull_signal = True
                if below and not bear_done:
                    work.at[timestamp, "bear_signal"] = True
                    bear_done = True
                    bear_signal = True

    current_date = dates[-1]
    current_rows = work[work["local_date"] == current_date]
    current_bias = str(current_rows["bias"].iloc[-1]) if not current_rows.empty else "SIN NIVELES"
    warning = latest_warning
    if missing_by_day[current_date]:
        warning = (
            f"{current_date}: {_format_missing(missing_by_day[current_date])}. "
            "La actualización se publicará al siguiente día solo si está completa."
        )
    return DailyLevelResult(
        work.drop(columns=["local_time", "local_date"]),
        active_date,
        active_levels,
        warning,
        current_bias,
        bull_signal,
        bear_signal,
    )
