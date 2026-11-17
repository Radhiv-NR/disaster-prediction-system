"""Create calibration readings for training and local simulator updates."""
from pathlib import Path

import numpy as np
import pandas as pd

from config import settings

FEATURE_COLS = [
    "temperature_c",
    "humidity_pct",
    "rainfall_mm",
    "wind_speed_kmh",
    "pressure_hpa",
    "river_level_m",
    "seismic_magnitude",
    "soil_moisture_pct",
]

LABEL_COL = "disaster_type"
RISK_ORDER = {"none": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}


def load_regional_data() -> pd.DataFrame:
    """Load Andhra Pradesh / Telangana labelled examples from CSV."""
    path = Path(settings.REGIONAL_CSV)
    if not path.exists():
        return pd.DataFrame()
    df = pd.read_csv(path, comment="#")
    # Keep only training-relevant columns
    keep = FEATURE_COLS + [LABEL_COL, "risk_level"]
    available = [c for c in keep if c in df.columns]
    return df[available].dropna(subset=[LABEL_COL])


def _synth_row(rng: np.random.Generator, disaster: str) -> dict:
    """One physically-plausible synthetic sensor row."""
    if disaster == "flood":
        return {
            "temperature_c": rng.uniform(24, 34),
            "humidity_pct": rng.uniform(80, 99),
            "rainfall_mm": rng.uniform(80, 250),
            "wind_speed_kmh": rng.uniform(10, 60),
            "pressure_hpa": rng.uniform(990, 1010),
            "river_level_m": rng.uniform(4.0, 9.0),
            "seismic_magnitude": rng.uniform(0.0, 1.5),
            "soil_moisture_pct": rng.uniform(70, 100),
            "disaster_type": "flood",
            "risk_level": rng.choice(["high", "critical"], p=[0.4, 0.6]),
        }
    if disaster == "cyclone":
        return {
            "temperature_c": rng.uniform(26, 32),
            "humidity_pct": rng.uniform(85, 99),
            "rainfall_mm": rng.uniform(60, 200),
            "wind_speed_kmh": rng.uniform(90, 200),
            "pressure_hpa": rng.uniform(940, 980),
            "river_level_m": rng.uniform(2.0, 6.0),
            "seismic_magnitude": rng.uniform(0.0, 1.0),
            "soil_moisture_pct": rng.uniform(60, 95),
            "disaster_type": "cyclone",
            "risk_level": rng.choice(["high", "critical"], p=[0.35, 0.65]),
        }
    if disaster == "earthquake":
        return {
            "temperature_c": rng.uniform(20, 36),
            "humidity_pct": rng.uniform(40, 80),
            "rainfall_mm": rng.uniform(0, 30),
            "wind_speed_kmh": rng.uniform(5, 30),
            "pressure_hpa": rng.uniform(1000, 1020),
            "river_level_m": rng.uniform(0.5, 3.0),
            "seismic_magnitude": rng.uniform(4.5, 7.5),
            "soil_moisture_pct": rng.uniform(20, 60),
            "disaster_type": "earthquake",
            "risk_level": rng.choice(["high", "critical"], p=[0.45, 0.55]),
        }
    if disaster == "wildfire":
        return {
            "temperature_c": rng.uniform(35, 48),
            "humidity_pct": rng.uniform(10, 35),
            "rainfall_mm": rng.uniform(0, 5),
            "wind_speed_kmh": rng.uniform(20, 70),
            "pressure_hpa": rng.uniform(1005, 1025),
            "river_level_m": rng.uniform(0.2, 2.0),
            "seismic_magnitude": rng.uniform(0.0, 1.0),
            "soil_moisture_pct": rng.uniform(5, 25),
            "disaster_type": "wildfire",
            "risk_level": rng.choice(["high", "critical"], p=[0.4, 0.6]),
        }
    # calm / none
    return {
        "temperature_c": rng.uniform(22, 34),
        "humidity_pct": rng.uniform(40, 75),
        "rainfall_mm": rng.uniform(0, 20),
        "wind_speed_kmh": rng.uniform(5, 35),
        "pressure_hpa": rng.uniform(1005, 1018),
        "river_level_m": rng.uniform(0.5, 3.0),
        "seismic_magnitude": rng.uniform(0.0, 2.0),
        "soil_moisture_pct": rng.uniform(25, 60),
        "disaster_type": "none",
        "risk_level": rng.choice(["none", "low"], p=[0.7, 0.3]),
    }


def generate_dataset(n_per_class: int = 400, seed: int = 42) -> pd.DataFrame:
    """
    Build training data:
            - bulk calibration rows covering physically plausible weather scenarios

        Regional CSV data is intentionally excluded. Live predictions use only
        current weather observations from the weather provider.
    """
    rng = np.random.default_rng(seed)
    classes = ["flood", "cyclone", "wildfire", "none"]
    rows = []
    for cls in classes:
        for _ in range(n_per_class):
            rows.append(_synth_row(rng, cls))
    synth = pd.DataFrame(rows)

    return synth.sample(frac=1.0, random_state=seed).reset_index(drop=True)


# Coastal AP cities — higher cyclone probability
_COASTAL_AP = {
    "Visakhapatnam", "Kakinada", "Nellore", "Machilipatnam", "Ongole", "Srikakulam",
}
# Godavari / Krishna flood-prone
_FLOOD_PRONE = {
    "Vijayawada", "Rajahmundry", "Khammam", "Bhadrachalam", "Nizamabad", "Eluru", "Nalgonda",
}
# Dry / forest fire-prone inland
_FIRE_PRONE = {
    "Adilabad", "Anantapur", "Kadapa", "Kurnool", "Nalgonda", "Karimnagar", "Araku", "Nallamala",
}


def random_live_reading(region: dict, rng: np.random.Generator | None = None) -> dict:
    """
    Live sensor packet for AP/Telangana stations only.
    Disaster mix is biased by local geography (coast → cyclone, rivers → flood, dry hills → wildfire).
    """
    rng = rng or np.random.default_rng()
    name = region.get("name", "")
    state = region.get("state", "")

    roll = rng.random()
    if name in _COASTAL_AP:
        # Coast: more cyclone + flood, rare wildfire
        if roll < 0.68:
            profile = "none"
        elif roll < 0.80:
            profile = "cyclone"
        elif roll < 0.92:
            profile = "flood"
        elif roll < 0.97:
            profile = "earthquake"
        else:
            profile = "wildfire"
    elif name in _FLOOD_PRONE:
        if roll < 0.68:
            profile = "none"
        elif roll < 0.86:
            profile = "flood"
        elif roll < 0.92:
            profile = "earthquake"
        elif roll < 0.97:
            profile = "cyclone" if "Andhra" in state or name in {"Khammam"} else "none"
        else:
            profile = "wildfire"
    elif name in _FIRE_PRONE:
        if roll < 0.70:
            profile = "none"
        elif roll < 0.86:
            profile = "wildfire"
        elif roll < 0.93:
            profile = "earthquake"
        elif roll < 0.97:
            profile = "flood"
        else:
            profile = "cyclone"
    else:
        # Generic inland (Hyderabad, Warangal, Tirupati, …)
        if roll < 0.74:
            profile = "none"
        elif roll < 0.84:
            profile = "flood"
        elif roll < 0.90:
            profile = "earthquake"
        elif roll < 0.95:
            profile = "wildfire"
        else:
            profile = "cyclone"

    row = _synth_row(rng, profile)
    return {
        "station_id": region["station_id"],
        "region_name": region["name"],
        "latitude": region["latitude"],
        "longitude": region["longitude"],
        "temperature_c": round(row["temperature_c"], 1),
        "humidity_pct": round(row["humidity_pct"], 1),
        "rainfall_mm": round(row["rainfall_mm"], 1),
        "wind_speed_kmh": round(row["wind_speed_kmh"], 1),
        "pressure_hpa": round(row["pressure_hpa"], 1),
        "river_level_m": round(row["river_level_m"], 2),
        "seismic_magnitude": round(row["seismic_magnitude"], 2),
        "soil_moisture_pct": round(row["soil_moisture_pct"], 1),
    }
