"""Read application settings from the project's .env file."""
import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


class Config:
    # Database connection. SQLite is selected by database.py when MySQL is unavailable.
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
    MODEL_PATH = BASE_DIR / "models" / "weather_disaster_model.joblib"
    LOG_DIR = BASE_DIR / "logs"

    # Background workers and alert timing.
    SIMULATOR_ENABLED = os.getenv("SIMULATOR_ENABLED", "true").lower() in ("1", "true", "yes")
    SIMULATOR_INTERVAL_SECONDS = float(os.getenv("SIMULATOR_INTERVAL_SECONDS", "4"))
    ALERT_MAX_AGE_SECONDS = int(os.getenv("ALERT_MAX_AGE_SECONDS", "1800"))
    LIVE_ALERTS_ENABLED = os.getenv("LIVE_ALERTS_ENABLED", "true").lower() in ("1", "true", "yes")
    LIVE_ALERT_INTERVAL_SECONDS = int(os.getenv("LIVE_ALERT_INTERVAL_SECONDS", "300"))

    # Open-Meteo weather and map settings.
    WEATHER_ENABLED = os.getenv("WEATHER_ENABLED", "true").lower() in ("1", "true", "yes")
    WEATHER_PROVIDER = os.getenv("WEATHER_PROVIDER", "open_meteo").lower()
    WEATHER_CACHE_SECONDS = int(os.getenv("WEATHER_CACHE_SECONDS", "300"))
    WEATHER_TIMEOUT_SECONDS = float(os.getenv("WEATHER_TIMEOUT_SECONDS", "8"))
    OPEN_METEO_API_URL = os.getenv(
        "OPEN_METEO_API_URL", "https://api.open-meteo.com/v1/forecast"
    )
    GOOGLE_WEATHER_API_URL = os.getenv(
        "GOOGLE_WEATHER_API_URL",
        "https://weather.googleapis.com/v1/currentConditions:lookup",
    )
    GOOGLE_MAPS_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY", "").strip()
    GOOGLE_WEATHER_API_KEY = os.getenv(
        "GOOGLE_WEATHER_API_KEY", GOOGLE_MAPS_API_KEY
    ).strip()

    # TTS
    TTS_ENABLED = os.getenv("TTS_ENABLED", "true").lower() in ("1", "true", "yes")
    TTS_MIN_RISK = os.getenv("TTS_MIN_RISK", "high").lower()
    TTS_LANGUAGE = os.getenv("TTS_LANGUAGE", "en").lower()
    MACOS_NOTIFICATIONS_ENABLED = os.getenv(
        "MACOS_NOTIFICATIONS_ENABLED", "true"
    ).lower() in ("1", "true", "yes")
    MACOS_NOTIFICATIONS_MIN_RISK = os.getenv("MACOS_NOTIFICATIONS_MIN_RISK", "high").lower()

    # SIM7600 4G modem SMS
    SMS_ENABLED = os.getenv(
        "SMS_ENABLED", os.getenv("GSM_ENABLED", "false")
    ).lower() in ("1", "true", "yes")
    SMS_MIN_RISK = os.getenv("SMS_MIN_RISK", "high").lower()
    GSM_ENABLED = SMS_ENABLED
    GSM_PORT = os.getenv("GSM_PORT", "")
    GSM_BAUDRATE = int(os.getenv("GSM_BAUDRATE", "115200"))
    GSM_TO_NUMBERS = [
        n.strip()
        for n in os.getenv("GSM_TO_NUMBERS", "").split(",")
        if n.strip()
    ]

    # Free Telegram bot alerts. Use one group chat ID or comma-separated user IDs.
    TELEGRAM_ENABLED = os.getenv("TELEGRAM_ENABLED", "false").lower() in ("1", "true", "yes")
    TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    TELEGRAM_CHAT_IDS = [
        chat_id.strip()
        for chat_id in os.getenv("TELEGRAM_CHAT_IDS", "").split(",")
        if chat_id.strip()
    ]
    TELEGRAM_MIN_RISK = os.getenv("TELEGRAM_MIN_RISK", "high").lower()
    TELEGRAM_API_TIMEOUT_SECONDS = float(os.getenv("TELEGRAM_API_TIMEOUT_SECONDS", "10"))

    # SMTP email alerts
    EMAIL_ENABLED = os.getenv("EMAIL_ENABLED", "false").lower() in ("1", "true", "yes")
    EMAIL_MIN_RISK = os.getenv("EMAIL_MIN_RISK", "high").lower()
    EMAIL_FROM = os.getenv("EMAIL_FROM", "").strip()
    EMAIL_TO = [
        email.strip()
        for email in os.getenv("EMAIL_TO", "").split(",")
        if email.strip()
    ]
    SMTP_HOST = os.getenv("SMTP_HOST", "localhost").strip()
    SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
    SMTP_USERNAME = os.getenv("SMTP_USERNAME", "").strip()
    SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "").strip()
    SMTP_USE_TLS = os.getenv("SMTP_USE_TLS", "true").lower() in ("1", "true", "yes")
    SMTP_TIMEOUT_SECONDS = float(os.getenv("SMTP_TIMEOUT_SECONDS", "10"))

    # Server
    FLASK_HOST = os.getenv("FLASK_HOST", "127.0.0.1")
    FLASK_PORT = int(os.getenv("FLASK_PORT", "8000"))
    FLASK_DEBUG = os.getenv("FLASK_DEBUG", "false").lower() in ("1", "true", "yes")
    CORS_ORIGINS = [
        origin.strip()
        for origin in os.getenv(
            "CORS_ORIGINS", "http://127.0.0.1:8000,http://localhost:8000"
        ).split(",")
        if origin.strip()
    ]


settings = Config()
