"""Application configuration — loaded from .env via python-dotenv."""
import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


class Config:
    # Database
    DB_HOST = os.getenv("DB_HOST", "127.0.0.1")
    DB_PORT = int(os.getenv("DB_PORT", "3306"))
    DB_USER = os.getenv("DB_USER", "disaster_user")
    DB_PASSWORD = os.getenv("DB_PASSWORD", "change_me_strong_password")
    DB_NAME = os.getenv("DB_NAME", "disaster_prediction_db")

    @property
    def SQLALCHEMY_DATABASE_URI(self):
        return (
            f"mysql+mysqlconnector://{self.DB_USER}:{self.DB_PASSWORD}"
            f"@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"
        )

    # Paths
    BASE_DIR = BASE_DIR
    MODEL_PATH = BASE_DIR / "models" / "disaster_model.joblib"
    REGIONAL_CSV = BASE_DIR / "data" / "andhra_telangana_disasters.csv"
    LOG_DIR = BASE_DIR / "logs"

    # Simulator
    SIMULATOR_INTERVAL_SECONDS = float(os.getenv("SIMULATOR_INTERVAL_SECONDS", "4"))

    # TTS
    TTS_ENABLED = os.getenv("TTS_ENABLED", "true").lower() in ("1", "true", "yes")
    TTS_MIN_RISK = os.getenv("TTS_MIN_RISK", "high").lower()
    TTS_LANGUAGE = os.getenv("TTS_LANGUAGE", "en").lower()

    # SMS (Twilio)
    SMS_ENABLED = os.getenv("SMS_ENABLED", "false").lower() in ("1", "true", "yes")
    SMS_MIN_RISK = os.getenv("SMS_MIN_RISK", "critical").lower()
    TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID", "")
    TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN", "")
    TWILIO_FROM_NUMBER = os.getenv("TWILIO_FROM_NUMBER", "")
    SMS_TO_NUMBERS = [
        n.strip()
        for n in os.getenv("SMS_TO_NUMBERS", "").split(",")
        if n.strip()
    ]

    # Server
    FLASK_HOST = os.getenv("FLASK_HOST", "127.0.0.1")
    FLASK_PORT = int(os.getenv("FLASK_PORT", "8000"))
    FLASK_DEBUG = os.getenv("FLASK_DEBUG", "true").lower() in ("1", "true", "yes")


settings = Config()
