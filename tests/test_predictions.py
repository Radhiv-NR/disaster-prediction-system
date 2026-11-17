import pytest

from model_training import _weather_hazard, predict_disaster


def test_weather_hazard_prioritizes_cyclone_conditions():
    hazard, reason = _weather_hazard(
        {
            "temperature_c": 28,
            "humidity_pct": 90,
            "rainfall_mm": 100,
            "wind_speed_kmh": 80,
            "pressure_hpa": 980,
        }
    )

    assert hazard == "cyclone"
    assert "wind" in reason.lower()


def test_weather_hazard_detects_hot_dry_wildfire_conditions():
    hazard, _ = _weather_hazard(
        {
            "temperature_c": 42,
            "humidity_pct": 20,
            "rainfall_mm": 0,
            "wind_speed_kmh": 30,
            "pressure_hpa": 1012,
        }
    )

    assert hazard == "wildfire"


def test_prediction_returns_calm_result_without_loading_model():
    result = predict_disaster(
        {
            "temperature_c": 29,
            "humidity_pct": 55,
            "rainfall_mm": 4,
            "wind_speed_kmh": 18,
            "pressure_hpa": 1012,
        }
    )

    assert result["disaster_type"] == "none"
    assert result["risk_level"] == "none"
    assert result["confidence"] == 1.0


def test_prediction_rejects_missing_weather_fields():
    with pytest.raises(ValueError, match="Missing weather fields"):
        predict_disaster({"temperature_c": 25})
