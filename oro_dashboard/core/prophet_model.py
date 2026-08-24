"""Entrenamiento y prediccion Prophet, cacheado como recurso (evita reentrenar en cada rerun)."""
from __future__ import annotations

import pandas as pd
import streamlit as st
from prophet import Prophet


@st.cache_resource(ttl=900, show_spinner=False)
def train_and_forecast(df: pd.DataFrame, horizon_periods: int = 30, freq: str = "D") -> pd.DataFrame:
    """Entrena Prophet sobre el cierre historico y devuelve el forecast (historico + horizonte)."""
    idx = pd.to_datetime(df.index)
    if idx.tz is not None:
        idx = idx.tz_localize(None)

    prophet_df = pd.DataFrame({"ds": idx, "y": df["close"].astype(float).values}).dropna()

    model = Prophet(daily_seasonality=True, yearly_seasonality=True, interval_width=0.95)
    model.fit(prophet_df)

    future = model.make_future_dataframe(periods=horizon_periods, freq=freq)
    return model.predict(future)


def trend_label(forecast: pd.DataFrame, lookback: int = 10) -> tuple[str, float]:
    """Tendencia emergente: pendiente media de las ultimas N predicciones."""
    trend = float(forecast["yhat"].diff().tail(lookback).mean())
    label = "📈 Posible bandera alcista" if trend > 0 else "📉 Posible cuña descendente"
    return label, trend
