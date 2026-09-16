"""Clasificador ML (scikit-learn) de order blocks: complementa -no reemplaza- la
formula estadistica de `core.smc_zones.zone_probability`, entrenado sobre el
historial real de zonas que ya genera `detect_order_blocks`.
"""
from __future__ import annotations

import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, roc_auc_score
from sklearn.model_selection import train_test_split

from .smc_zones import atr, detect_order_blocks

FEATURE_NAMES = ["height_atr_ratio", "impulse_bars", "is_bullish"]
MIN_SAMPLE_SIZE = 30


def _zone_features(df: pd.DataFrame, zones: list[dict]) -> pd.DataFrame:
    atr_series = atr(df)
    rows = []
    for z in zones:
        if z["status"] not in ("continuo", "fallo"):
            continue
        atr_at_formation = float(atr_series.iloc[z["ob_idx"]]) or 1e-9
        height = z["top"] - z["bottom"]
        rows.append(
            {
                "height_atr_ratio": height / atr_at_formation,
                "impulse_bars": z["break_idx"] - z["ob_idx"],
                "is_bullish": int(z["kind"] == "bullish"),
                "label": int(z["status"] == "continuo"),
            }
        )
    return pd.DataFrame(rows)


def train_zone_classifier(df: pd.DataFrame, lookback: int = 5, max_zones: int = 500) -> dict:
    """Entrena un RandomForest sobre las zonas resueltas de `df`. Devuelve
    accuracy/AUC frente a la baseline (predecir siempre la clase mayoritaria) —
    `beats_baseline` deja claro si el modelo realmente aporta algo."""
    zones = detect_order_blocks(df, lookback=lookback, max_zones=max_zones)
    features = _zone_features(df, zones)

    if len(features) < MIN_SAMPLE_SIZE:
        return {"trained": False, "reason": f"Muestra insuficiente ({len(features)} zonas resueltas, se requieren >= {MIN_SAMPLE_SIZE})."}

    X, y = features[FEATURE_NAMES], features["label"]
    stratify = y if y.nunique() > 1 else None
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.3, random_state=42, stratify=stratify)

    model = RandomForestClassifier(n_estimators=200, max_depth=4, min_samples_leaf=5, random_state=42)
    model.fit(X_train, y_train)

    y_pred = model.predict(X_test)
    y_proba = model.predict_proba(X_test)[:, 1]
    accuracy = accuracy_score(y_test, y_pred)
    try:
        auc = roc_auc_score(y_test, y_proba) if y_test.nunique() > 1 else None
    except ValueError:
        auc = None

    baseline_accuracy = max(y.mean(), 1 - y.mean())

    return {
        "trained": True,
        "model": model,
        "accuracy": accuracy,
        "auc": auc,
        "baseline_accuracy": baseline_accuracy,
        "beats_baseline": accuracy > baseline_accuracy,
        "sample_size": len(features),
        "feature_importance": dict(zip(FEATURE_NAMES, model.feature_importances_)),
    }


def predict_zone_probability(model: RandomForestClassifier, zone: dict, atr_value: float) -> float | None:
    """Probabilidad (%) de que `zone` continue, segun el modelo entrenado."""
    if atr_value <= 0:
        return None
    height = zone["top"] - zone["bottom"]
    features = pd.DataFrame(
        [
            {
                "height_atr_ratio": height / atr_value,
                "impulse_bars": zone["break_idx"] - zone["ob_idx"],
                "is_bullish": int(zone["kind"] == "bullish"),
            }
        ]
    )[FEATURE_NAMES]
    return float(model.predict_proba(features)[0, 1] * 100)
