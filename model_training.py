"""Train and use the weather-risk classifier."""
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, classification_report
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from config import settings
from disaster_data_generator import FEATURE_COLS, LABEL_COL, generate_dataset

WEATHER_FEATURE_COLS = [
    "temperature_c",
    "humidity_pct",
    "rainfall_mm",
    "wind_speed_kmh",
    "pressure_hpa",
]
WEATHER_LABELS = ("flood", "cyclone", "wildfire", "none")

_model = None


def train_and_save(n_per_class: int = 400) -> dict:
    """Train a weather-only model from generated calibration scenarios."""
    df = generate_dataset(n_per_class=n_per_class)
    X = df[WEATHER_FEATURE_COLS]
    y = df[LABEL_COL]

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42, stratify=y
    )

    pipe = Pipeline(
        [
            ("scaler", StandardScaler()),
            (
                "clf",
                RandomForestClassifier(
                    n_estimators=120,
                    max_depth=12,
                    min_samples_leaf=2,
                    random_state=42,
                    n_jobs=-1,
                ),
            ),
        ]
    )
    pipe.fit(X_train, y_train)
    preds = pipe.predict(X_test)
    acc = accuracy_score(y_test, preds)

    path = Path(settings.MODEL_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(pipe, path)

    global _model
    _model = pipe

    return {
        "accuracy": float(acc),
        "n_train": len(X_train),
        "n_test": len(X_test),
        "report": classification_report(y_test, preds, zero_division=0),
        "path": str(path),
    }


def load_model():
    global _model
    if _model is not None:
        return _model
    path = Path(settings.MODEL_PATH)
    if path.exists():
        _model = joblib.load(path)
        return _model
    train_and_save()
    return _model


def _risk_from_proba(label: str, proba: float) -> str:
    if label == "none":
        return "none" if proba > 0.6 else "low"
    if proba >= 0.85:
        return "critical"
    if proba >= 0.65:
        return "high"
    if proba >= 0.45:
        return "medium"
    return "low"


def _weather_hazard(features: dict) -> tuple[str, str]:
    """Return a weather-supported hazard; weather cannot identify earthquakes."""
    rainfall = float(features["rainfall_mm"])
    wind = float(features["wind_speed_kmh"])
    pressure = float(features["pressure_hpa"])
    temperature = float(features["temperature_c"])
    humidity = float(features["humidity_pct"])

    if wind >= 62 and pressure <= 990:
        return "cyclone", "Strong wind and low pressure indicate cyclone conditions."
    if rainfall >= 20 and humidity >= 80:
        return "flood", "Heavy current rainfall and high humidity indicate flood risk."
    if temperature >= 35 and humidity <= 35 and rainfall <= 1:
        return "wildfire", "Hot, dry conditions indicate elevated wildfire risk."
    return "none", "Current weather does not meet a severe weather threshold."


def predict_disaster(features: dict) -> dict:
    """Return a hazard, risk level, confidence, and supporting probabilities."""
    missing = [c for c in WEATHER_FEATURE_COLS if features.get(c) is None]
    if missing:
        raise ValueError(f"Missing weather fields: {', '.join(missing)}")
    hazard, reason = _weather_hazard(features)
    if hazard == "none":
        return {
            "disaster_type": "none",
            "risk_level": "none",
            "confidence": 1.0,
            "probabilities": {label: (1.0 if label == "none" else 0.0) for label in WEATHER_LABELS},
            "reason": reason,
        }

    model = load_model()
    row = pd.DataFrame([{c: float(features[c]) for c in WEATHER_FEATURE_COLS}])
    proba_vec = model.predict_proba(row)[0]
    classes = list(model.classes_)
    best_idx = int(np.argmax(proba_vec))
    label = hazard
    confidence = float(proba_vec[classes.index(hazard)]) if hazard in classes else 0.5
    risk = "critical" if hazard == "cyclone" and confidence >= 0.85 else "high"
    return {
        "disaster_type": label,
        "risk_level": risk,
        "confidence": round(confidence, 4),
        "probabilities": {c: round(float(p), 4) for c, p in zip(classes, proba_vec)},
        "reason": reason,
    }
