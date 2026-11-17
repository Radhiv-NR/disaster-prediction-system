"""SQLAlchemy engine, session factory, ORM models, and region seeding."""
from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    Integer,
    String,
    Text,
    create_engine,
)
from sqlalchemy.orm import declarative_base, sessionmaker

from config import settings

# Prefer MySQL; fall back to SQLite for local/dev without a server
try:
    engine = create_engine(
        settings.SQLALCHEMY_DATABASE_URI,
        pool_pre_ping=True,
        pool_recycle=3600,
    )
    # Quick connectivity probe
    with engine.connect() as _:
        pass
except Exception:
    sqlite_path = settings.BASE_DIR / "data" / "disaster_local.db"
    engine = create_engine(f"sqlite:///{sqlite_path}", connect_args={"check_same_thread": False})

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class Region(Base):
    __tablename__ = "regions"

    id = Column(Integer, primary_key=True)
    name = Column(String(120), unique=True, nullable=False)
    state = Column(String(60), nullable=False)
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    station_id = Column(String(40), unique=True, nullable=False)


class SensorReading(Base):
    __tablename__ = "sensor_readings"

    id = Column(Integer, primary_key=True)
    station_id = Column(String(40), nullable=False, index=True)
    region_name = Column(String(120), nullable=False)
    latitude = Column(Float)
    longitude = Column(Float)
    temperature_c = Column(Float)
    humidity_pct = Column(Float)
    rainfall_mm = Column(Float)
    wind_speed_kmh = Column(Float)
    pressure_hpa = Column(Float)
    river_level_m = Column(Float)
    seismic_magnitude = Column(Float)
    soil_moisture_pct = Column(Float)
    recorded_at = Column(DateTime, default=datetime.utcnow, index=True)


class PredictionLog(Base):
    __tablename__ = "prediction_logs"

    id = Column(Integer, primary_key=True)
    station_id = Column(String(40), nullable=False)
    region_name = Column(String(120), nullable=False)
    predicted_type = Column(String(40), nullable=False)
    risk_level = Column(String(20), nullable=False)
    confidence = Column(Float)
    features_json = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


class Alert(Base):
    __tablename__ = "alerts"

    id = Column(Integer, primary_key=True)
    region_name = Column(String(120), nullable=False)
    disaster_type = Column(String(40), nullable=False)
    risk_level = Column(String(20), nullable=False)
    message = Column(Text)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


# 14 cities across Andhra Pradesh & Telangana
DEFAULT_REGIONS = [
    # Andhra Pradesh
    {"name": "Visakhapatnam", "state": "Andhra Pradesh", "latitude": 17.6868, "longitude": 83.2185, "station_id": "AP-VSKP"},
    {"name": "Vijayawada", "state": "Andhra Pradesh", "latitude": 16.5062, "longitude": 80.6480, "station_id": "AP-VJA"},
    {"name": "Rajahmundry", "state": "Andhra Pradesh", "latitude": 17.0005, "longitude": 81.8040, "station_id": "AP-RJY"},
    {"name": "Kakinada", "state": "Andhra Pradesh", "latitude": 16.9891, "longitude": 82.2475, "station_id": "AP-KKD"},
    {"name": "Nellore", "state": "Andhra Pradesh", "latitude": 14.4426, "longitude": 79.9865, "station_id": "AP-NLR"},
    {"name": "Tirupati", "state": "Andhra Pradesh", "latitude": 13.6288, "longitude": 79.4192, "station_id": "AP-TPTY"},
    {"name": "Kurnool", "state": "Andhra Pradesh", "latitude": 15.8281, "longitude": 78.0373, "station_id": "AP-KNL"},
    {"name": "Anantapur", "state": "Andhra Pradesh", "latitude": 14.6819, "longitude": 77.6006, "station_id": "AP-ATP"},
    # Telangana
    {"name": "Hyderabad", "state": "Telangana", "latitude": 17.3850, "longitude": 78.4867, "station_id": "TS-HYD"},
    {"name": "Warangal", "state": "Telangana", "latitude": 17.9689, "longitude": 79.5941, "station_id": "TS-WGL"},
    {"name": "Khammam", "state": "Telangana", "latitude": 17.2473, "longitude": 80.1514, "station_id": "TS-KMM"},
    {"name": "Nizamabad", "state": "Telangana", "latitude": 18.6725, "longitude": 78.0941, "station_id": "TS-NZB"},
    {"name": "Karimnagar", "state": "Telangana", "latitude": 18.4386, "longitude": 79.1288, "station_id": "TS-KRM"},
    {"name": "Adilabad", "state": "Telangana", "latitude": 19.6641, "longitude": 78.5320, "station_id": "TS-ADB"},
]


def init_db():
    """Create tables and seed default regions if empty."""
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        if db.query(Region).count() == 0:
            for r in DEFAULT_REGIONS:
                db.add(Region(**r))
            db.commit()
    finally:
        db.close()


def get_db():
    """Request-scoped session helper."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
