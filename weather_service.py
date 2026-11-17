"""Fetch current weather and cache each location briefly."""
from __future__ import annotations

import logging
import threading
import time

import requests

from config import settings

logger = logging.getLogger(__name__)
_cache: dict[tuple[float, float], tuple[float, dict]] = {}
_cache_lock = threading.Lock()


def _get_google_weather(latitude: float, longitude: float) -> dict:
    response = requests.get(
        settings.GOOGLE_WEATHER_API_URL,
        params={
            "key": settings.GOOGLE_WEATHER_API_KEY,
            "location.latitude": latitude,
            "location.longitude": longitude,
        },
        timeout=settings.WEATHER_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    payload = response.json()
    temperature = payload.get("temperature", {})
    wind = payload.get("wind", {})
    wind_speed = wind.get("speed", {})
    precipitation = payload.get("precipitation", {}).get("qpf", {}).get("quantity", 0.0)
    pressure = payload.get("airPressure", {})
    wind_speed_value = float(wind_speed.get("value", 0.0))
    if wind_speed.get("unit") == "MILES_PER_HOUR":
        wind_speed_value *= 1.609344
    elif wind_speed.get("unit") == "METERS_PER_SECOND":
        wind_speed_value *= 3.6
    rainfall_value = float(precipitation.get("value", 0.0)) if isinstance(precipitation, dict) else float(precipitation)
    if isinstance(precipitation, dict) and precipitation.get("unit") == "INCHES":
        rainfall_value *= 25.4
    return {
        "temperature_c": float(temperature["degrees"]),
        "humidity_pct": float(payload["relativeHumidity"]),
        "rainfall_mm": rainfall_value,
        "wind_speed_kmh": wind_speed_value,
        "pressure_hpa": float(pressure.get("meanSeaLevelMillibars", 0.0)),
        "observed_at": payload.get("currentTime"),
        "source": "google-weather",
        "is_live": True,
        "provider_latitude": payload.get("location", {}).get("latitude", latitude),
        "provider_longitude": payload.get("location", {}).get("longitude", longitude),
        "elevation_m": payload.get("elevationMeters"),
    }


def _get_open_meteo_weather(latitude: float, longitude: float) -> dict:
    response = requests.get(
        settings.OPEN_METEO_API_URL,
        params={
            "latitude": latitude,
            "longitude": longitude,
            "current": (
                "temperature_2m,relative_humidity_2m,precipitation,"
                "wind_speed_10m,surface_pressure"
            ),
            "wind_speed_unit": "kmh",
            "timezone": "UTC",
        },
        timeout=settings.WEATHER_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    current = response.json()["current"]
    return {
        "temperature_c": float(current["temperature_2m"]),
        "humidity_pct": float(current["relative_humidity_2m"]),
        "rainfall_mm": float(current.get("precipitation", 0.0)),
        "wind_speed_kmh": float(current["wind_speed_10m"]),
        "pressure_hpa": float(current["surface_pressure"]),
        "observed_at": current.get("time"),
        "source": "open-meteo",
        "is_live": True,
        "provider_latitude": latitude,
        "provider_longitude": longitude,
    }


def get_current_weather_bulk(locations: list[tuple[float, float]]) -> list[dict | None]:
    """Fetch current observations for the requested locations."""
    if not locations:
        return []
    return [try_get_current_weather(latitude, longitude) for latitude, longitude in locations]


def get_current_weather(latitude: float, longitude: float) -> dict:
    """Return current weather values in the feature names used by the model."""
    key = (round(float(latitude), 4), round(float(longitude), 4))
    if not (-90 <= key[0] <= 90 and -180 <= key[1] <= 180):
        raise ValueError("Coordinates are outside valid latitude/longitude ranges")
    now = time.monotonic()
    with _cache_lock:
        cached = _cache.get(key)
        if cached and now - cached[0] < settings.WEATHER_CACHE_SECONDS:
            return cached[1].copy()

    if settings.WEATHER_PROVIDER in ("open_meteo", "open-meteo"):
        weather = _get_open_meteo_weather(key[0], key[1])
    elif settings.WEATHER_PROVIDER == "google":
        if not settings.GOOGLE_WEATHER_API_KEY:
            raise ValueError("GOOGLE_WEATHER_API_KEY is not configured")
        weather = _get_google_weather(key[0], key[1])
    else:
        raise ValueError(f"Unsupported weather provider: {settings.WEATHER_PROVIDER}")
    with _cache_lock:
        _cache[key] = (now, weather)
    return weather.copy()


def try_get_current_weather(latitude: float, longitude: float) -> dict | None:
    """Return weather when available; callers can fall back to simulation."""
    if not settings.WEATHER_ENABLED:
        return None
    try:
        return get_current_weather(latitude, longitude)
    except (KeyError, TypeError, ValueError, requests.RequestException) as exc:
        logger.warning("Weather lookup failed for %s,%s: %s", latitude, longitude, exc)
        return None