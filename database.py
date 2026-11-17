"""Database setup, ORM models, and the default monitoring regions."""
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


class SmsRecipient(Base):
    __tablename__ = "sms_recipients"

    id = Column(Integer, primary_key=True)
    phone_number = Column(String(20), unique=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)


# District headquarters across Andhra Pradesh and Telangana.
DEFAULT_REGIONS = [
    # Andhra Pradesh
    {"name": "Alluri Sitharama Raju", "state": "Andhra Pradesh", "latitude": 18.0815, "longitude": 82.6673, "station_id": "AP-ASR"},
    {"name": "Anakapalli", "state": "Andhra Pradesh", "latitude": 17.6913, "longitude": 83.0039, "station_id": "AP-AKP"},
    {"name": "Anantapuramu", "state": "Andhra Pradesh", "latitude": 14.6819, "longitude": 77.6006, "station_id": "AP-ATP"},
    {"name": "Annamayya", "state": "Andhra Pradesh", "latitude": 14.0574, "longitude": 79.0520, "station_id": "AP-ANN"},
    {"name": "Bapatla", "state": "Andhra Pradesh", "latitude": 15.9044, "longitude": 80.4675, "station_id": "AP-BPT"},
    {"name": "Chittoor", "state": "Andhra Pradesh", "latitude": 13.2172, "longitude": 79.1003, "station_id": "AP-CTR"},
    {"name": "Konaseema", "state": "Andhra Pradesh", "latitude": 16.5787, "longitude": 82.0061, "station_id": "AP-KNS"},
    {"name": "East Godavari", "state": "Andhra Pradesh", "latitude": 17.0005, "longitude": 81.8040, "station_id": "AP-EG"},
    {"name": "Eluru", "state": "Andhra Pradesh", "latitude": 16.7107, "longitude": 81.0952, "station_id": "AP-ELR"},
    {"name": "Guntur", "state": "Andhra Pradesh", "latitude": 16.3067, "longitude": 80.4365, "station_id": "AP-GNT"},
    {"name": "Kakinada", "state": "Andhra Pradesh", "latitude": 16.9891, "longitude": 82.2475, "station_id": "AP-KKD"},
    {"name": "Krishna", "state": "Andhra Pradesh", "latitude": 16.1875, "longitude": 81.1389, "station_id": "AP-MMT"},
    {"name": "Kurnool", "state": "Andhra Pradesh", "latitude": 15.8281, "longitude": 78.0373, "station_id": "AP-KNL"},
    {"name": "Nandyal", "state": "Andhra Pradesh", "latitude": 15.4786, "longitude": 78.4871, "station_id": "AP-NDL"},
    {"name": "NTR", "state": "Andhra Pradesh", "latitude": 16.5062, "longitude": 80.6480, "station_id": "AP-VJA"},
    {"name": "Palnadu", "state": "Andhra Pradesh", "latitude": 16.2350, "longitude": 80.0498, "station_id": "AP-PLN"},
    {"name": "Parvathipuram Manyam", "state": "Andhra Pradesh", "latitude": 18.7811, "longitude": 83.4254, "station_id": "AP-PM"},
    {"name": "Prakasam", "state": "Andhra Pradesh", "latitude": 15.5057, "longitude": 80.0499, "station_id": "AP-ONG"},
    {"name": "Srikakulam", "state": "Andhra Pradesh", "latitude": 18.2949, "longitude": 83.8938, "station_id": "AP-SKLM"},
    {"name": "SPSR Nellore", "state": "Andhra Pradesh", "latitude": 14.4426, "longitude": 79.9865, "station_id": "AP-NLR"},
    {"name": "Sri Sathya Sai", "state": "Andhra Pradesh", "latitude": 14.1652, "longitude": 77.8100, "station_id": "AP-SSS"},
    {"name": "Tirupati", "state": "Andhra Pradesh", "latitude": 13.6288, "longitude": 79.4192, "station_id": "AP-TPTY"},
    {"name": "Visakhapatnam", "state": "Andhra Pradesh", "latitude": 17.6868, "longitude": 83.2185, "station_id": "AP-VSKP"},
    {"name": "Vizianagaram", "state": "Andhra Pradesh", "latitude": 18.1067, "longitude": 83.3956, "station_id": "AP-VZM"},
    {"name": "West Godavari", "state": "Andhra Pradesh", "latitude": 16.5449, "longitude": 81.5212, "station_id": "AP-WG"},
    {"name": "YSR Kadapa", "state": "Andhra Pradesh", "latitude": 14.4674, "longitude": 78.8241, "station_id": "AP-CDP"},
    # Telangana
    {"name": "Hyderabad", "state": "Telangana", "latitude": 17.3850, "longitude": 78.4867, "station_id": "TS-HYD"},
    {"name": "Bhadradri Kothagudem", "state": "Telangana", "latitude": 17.5553, "longitude": 80.6175, "station_id": "TS-KGM"},
    {"name": "Hanamkonda", "state": "Telangana", "latitude": 17.9784, "longitude": 79.5941, "station_id": "TS-HNK"},
    {"name": "Warangal", "state": "Telangana", "latitude": 17.9689, "longitude": 79.5941, "station_id": "TS-WGL"},
    {"name": "Khammam", "state": "Telangana", "latitude": 17.2473, "longitude": 80.1514, "station_id": "TS-KMM"},
    {"name": "Nizamabad", "state": "Telangana", "latitude": 18.6725, "longitude": 78.0941, "station_id": "TS-NZB"},
    {"name": "Karimnagar", "state": "Telangana", "latitude": 18.4386, "longitude": 79.1288, "station_id": "TS-KRM"},
    {"name": "Adilabad", "state": "Telangana", "latitude": 19.6641, "longitude": 78.5320, "station_id": "TS-ADB"},
    {"name": "Nalgonda", "state": "Telangana", "latitude": 17.0575, "longitude": 79.2684, "station_id": "TS-NLG"},
    {"name": "Mahabubnagar", "state": "Telangana", "latitude": 16.7488, "longitude": 77.9850, "station_id": "TS-MBNR"},
    {"name": "Sangareddy", "state": "Telangana", "latitude": 17.6248, "longitude": 78.0834, "station_id": "TS-SGR"},
    {"name": "Suryapet", "state": "Telangana", "latitude": 17.1405, "longitude": 79.6236, "station_id": "TS-SRP"},
    {"name": "Medak", "state": "Telangana", "latitude": 18.0453, "longitude": 78.2608, "station_id": "TS-MDK"},
    {"name": "Jagtial", "state": "Telangana", "latitude": 18.7948, "longitude": 78.9166, "station_id": "TS-JTL"},
    {"name": "Jangaon", "state": "Telangana", "latitude": 17.7260, "longitude": 79.1520, "station_id": "TS-JGN"},
    {"name": "Jayashankar Bhupalpally", "state": "Telangana", "latitude": 18.4386, "longitude": 79.8649, "station_id": "TS-JBP"},
    {"name": "Jogulamba Gadwal", "state": "Telangana", "latitude": 16.2350, "longitude": 77.7956, "station_id": "TS-JGL"},
    {"name": "Kamareddy", "state": "Telangana", "latitude": 18.3215, "longitude": 78.3418, "station_id": "TS-KMR"},
    {"name": "Komaram Bheem Asifabad", "state": "Telangana", "latitude": 19.3585, "longitude": 79.2841, "station_id": "TS-KBA"},
    {"name": "Mahabubabad", "state": "Telangana", "latitude": 17.5973, "longitude": 80.0030, "station_id": "TS-MBD"},
    {"name": "Mancherial", "state": "Telangana", "latitude": 18.8756, "longitude": 79.4591, "station_id": "TS-MCL"},
    {"name": "Medchal-Malkajgiri", "state": "Telangana", "latitude": 17.6299, "longitude": 78.4814, "station_id": "TS-MED"},
    {"name": "Mulugu", "state": "Telangana", "latitude": 18.1905, "longitude": 79.9432, "station_id": "TS-MLG"},
    {"name": "Nagarkurnool", "state": "Telangana", "latitude": 16.4821, "longitude": 78.3247, "station_id": "TS-NK"},
    {"name": "Narayanpet", "state": "Telangana", "latitude": 16.7470, "longitude": 77.4956, "station_id": "TS-NPT"},
    {"name": "Nirmal", "state": "Telangana", "latitude": 19.0968, "longitude": 78.3441, "station_id": "TS-NRM"},
    {"name": "Peddapalli", "state": "Telangana", "latitude": 18.6136, "longitude": 79.3744, "station_id": "TS-PDL"},
    {"name": "Rajanna Sircilla", "state": "Telangana", "latitude": 18.3881, "longitude": 78.8101, "station_id": "TS-RSL"},
    {"name": "Rangareddy", "state": "Telangana", "latitude": 17.2403, "longitude": 78.4294, "station_id": "TS-RR"},
    {"name": "Siddipet", "state": "Telangana", "latitude": 18.1018, "longitude": 78.8520, "station_id": "TS-SDP"},
    {"name": "Vikarabad", "state": "Telangana", "latitude": 17.3381, "longitude": 77.9044, "station_id": "TS-VKB"},
    {"name": "Wanaparthy", "state": "Telangana", "latitude": 16.3623, "longitude": 78.0622, "station_id": "TS-WNP"},
    {"name": "Yadadri Bhuvanagiri", "state": "Telangana", "latitude": 17.5151, "longitude": 78.8856, "station_id": "TS-YBG"},
]


def init_db():
    """Create tables and add any missing default monitoring regions."""
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        default_station_ids = {region["station_id"] for region in DEFAULT_REGIONS}
        db.query(Region).filter(~Region.station_id.in_(default_station_ids)).delete(
            synchronize_session=False
        )
        existing_station_ids = {station_id for (station_id,) in db.query(Region.station_id).all()}
        missing_regions = [
            region for region in DEFAULT_REGIONS
            if region["station_id"] not in existing_station_ids
        ]
        if missing_regions:
            for r in missing_regions:
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
