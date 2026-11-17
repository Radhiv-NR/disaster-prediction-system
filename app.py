"""Real-Time Disaster Prediction System — Flask entrypoint."""
from __future__ import annotations

import json
import logging
import threading
import time
from datetime import datetime
from pathlib import Path

from flask import Flask, Response, jsonify, render_template, request, stream_with_context
from flask_cors import CORS

from alert_system import (
    broadcast,
    build_test_phrase,
    create_and_dispatch_alert,
    get_sms_status,
    get_tts_status,
    set_sms_enabled,
    set_tts_enabled,
    set_tts_language,
    speak_async,
    subscribe,
    test_sms,
    unsubscribe,
)
from config import settings
from database import (
    Alert,
    PredictionLog,
    Region,
    SensorReading,
    SessionLocal,
    init_db,
)
from disaster_data_generator import FEATURE_COLS, random_live_reading
from model_training import load_model, predict_disaster, train_and_save

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
settings.LOG_DIR.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(settings.LOG_DIR / "app.log"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger("app")

app = Flask(__name__)
CORS(app)

# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------
init_db()
try:
    stats = train_and_save() if not Path(settings.MODEL_PATH).exists() else None
    load_model()
    if stats:
        logger.info("ML model trained — accuracy=%.3f path=%s", stats["accuracy"], stats["path"])
    else:
        logger.info("ML model loaded from %s", settings.MODEL_PATH)
except Exception as exc:
    logger.exception("Model init failed: %s", exc)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------
def validate_reading(data: dict) -> tuple[dict | None, str | None]:
    required = ["station_id", "region_name"] + FEATURE_COLS
    missing = [k for k in required if k not in data]
    if missing:
        return None, f"Missing fields: {', '.join(missing)}"
    try:
        clean = {
            "station_id": str(data["station_id"])[:40],
            "region_name": str(data["region_name"])[:120],
            "latitude": float(data.get("latitude") or 0),
            "longitude": float(data.get("longitude") or 0),
        }
        for c in FEATURE_COLS:
            clean[c] = float(data[c])
        return clean, None
    except (TypeError, ValueError) as exc:
        return None, f"Invalid numeric value: {exc}"


def process_reading(db, data: dict) -> dict:
    """Persist sensor row → predict → log → maybe alert → broadcast."""
    reading = SensorReading(**{k: data[k] for k in data if hasattr(SensorReading, k)})
    db.add(reading)
    db.commit()
    db.refresh(reading)

    features = {c: data[c] for c in FEATURE_COLS}
    pred = predict_disaster(features)

    log = PredictionLog(
        station_id=data["station_id"],
        region_name=data["region_name"],
        predicted_type=pred["disaster_type"],
        risk_level=pred["risk_level"],
        confidence=pred["confidence"],
        features_json=json.dumps(features),
    )
    db.add(log)
    db.commit()

    event = {
        "type": "sensor",
        "station_id": data["station_id"],
        "region_name": data["region_name"],
        "latitude": data.get("latitude"),
        "longitude": data.get("longitude"),
        "features": features,
        "prediction": pred,
        "recorded_at": (reading.recorded_at or datetime.utcnow()).isoformat(),
    }
    broadcast("sensor", event)

    if pred["disaster_type"] != "none" and pred["risk_level"] in ("high", "critical"):
        create_and_dispatch_alert(
            db,
            Alert,
            region_name=data["region_name"],
            disaster_type=pred["disaster_type"],
            risk_level=pred["risk_level"],
        )

    return {"reading_id": reading.id, "prediction": pred}


# ---------------------------------------------------------------------------
# Background simulator
# ---------------------------------------------------------------------------
_sim_stop = threading.Event()


def _simulator_loop():
    logger.info("Simulator started (interval=%.1fs)", settings.SIMULATOR_INTERVAL_SECONDS)
    while not _sim_stop.is_set():
        db = SessionLocal()
        try:
            regions = db.query(Region).all()
            if not regions:
                time.sleep(settings.SIMULATOR_INTERVAL_SECONDS)
                continue
            # Cycle one region per tick
            idx = int(time.time() / settings.SIMULATOR_INTERVAL_SECONDS) % len(regions)
            r = regions[idx]
            region = {
                "name": r.name,
                "state": r.state,
                "station_id": r.station_id,
                "latitude": r.latitude,
                "longitude": r.longitude,
            }
            packet = random_live_reading(region)
            process_reading(db, packet)
        except Exception as exc:
            logger.warning("Simulator tick failed: %s", exc)
        finally:
            db.close()
        _sim_stop.wait(settings.SIMULATOR_INTERVAL_SECONDS)


_sim_thread = threading.Thread(target=_simulator_loop, daemon=True, name="simulator")
_sim_thread.start()


# ---------------------------------------------------------------------------
# Pages & static
# ---------------------------------------------------------------------------
@app.route("/")
def index():
    return render_template("index.html")


# ---------------------------------------------------------------------------
# Health / regions
# ---------------------------------------------------------------------------
@app.route("/api/health")
def health():
    return jsonify({"status": "ok", "time": datetime.utcnow().isoformat()})


@app.route("/api/regions")
def list_regions():
    db = SessionLocal()
    try:
        rows = db.query(Region).all()
        return jsonify(
            [
                {
                    "id": r.id,
                    "name": r.name,
                    "state": r.state,
                    "latitude": r.latitude,
                    "longitude": r.longitude,
                    "station_id": r.station_id,
                }
                for r in rows
            ]
        )
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Sensors & predictions
# ---------------------------------------------------------------------------
@app.route("/api/sensors/ingest", methods=["POST"])
def ingest_sensor():
    payload = request.get_json(silent=True) or {}
    clean, err = validate_reading(payload)
    if err:
        return jsonify({"error": err}), 400
    db = SessionLocal()
    try:
        result = process_reading(db, clean)
        return jsonify(result)
    finally:
        db.close()


@app.route("/api/predict", methods=["POST"])
def predict_only():
    payload = request.get_json(silent=True) or {}
    features = {}
    for c in FEATURE_COLS:
        try:
            features[c] = float(payload.get(c, 0))
        except (TypeError, ValueError):
            return jsonify({"error": f"Invalid value for {c}"}), 400
    return jsonify(predict_disaster(features))


@app.route("/api/alerts")
def list_alerts():
    db = SessionLocal()
    try:
        active_only = request.args.get("active", "1") != "0"
        q = db.query(Alert).order_by(Alert.created_at.desc()).limit(50)
        if active_only:
            q = q.filter(Alert.is_active.is_(True))
        rows = q.all()
        return jsonify(
            [
                {
                    "id": a.id,
                    "region_name": a.region_name,
                    "disaster_type": a.disaster_type,
                    "risk_level": a.risk_level,
                    "message": a.message,
                    "is_active": a.is_active,
                    "created_at": a.created_at.isoformat() if a.created_at else None,
                }
                for a in rows
            ]
        )
    finally:
        db.close()


@app.route("/api/telemetry")
def telemetry():
    db = SessionLocal()
    try:
        rows = (
            db.query(SensorReading)
            .order_by(SensorReading.recorded_at.desc())
            .limit(40)
            .all()
        )
        rows = list(reversed(rows))
        return jsonify(
            [
                {
                    "recorded_at": r.recorded_at.isoformat() if r.recorded_at else None,
                    "region_name": r.region_name,
                    "rainfall_mm": r.rainfall_mm,
                    "wind_speed_kmh": r.wind_speed_kmh,
                    "seismic_magnitude": r.seismic_magnitude,
                    "temperature_c": r.temperature_c,
                    "river_level_m": r.river_level_m,
                }
                for r in rows
            ]
        )
    finally:
        db.close()


# ---------------------------------------------------------------------------
# SSE live stream
# ---------------------------------------------------------------------------
@app.route("/stream/live")
def stream_live():
    def event_stream():
        q = subscribe()
        try:
            yield "event: connected\ndata: {\"ok\": true}\n\n"
            while True:
                try:
                    msg = q.get(timeout=25)
                    yield msg
                except Exception:
                    yield ": keepalive\n\n"
        finally:
            unsubscribe(q)

    return Response(
        stream_with_context(event_stream()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


# ---------------------------------------------------------------------------
# TTS endpoints
# ---------------------------------------------------------------------------
@app.route("/api/tts/status")
def tts_status():
    return jsonify(get_tts_status())


@app.route("/api/tts/toggle", methods=["POST"])
def tts_toggle():
    body = request.get_json(silent=True) or {}
    if "enabled" in body:
        set_tts_enabled(bool(body["enabled"]))
    else:
        st = get_tts_status()
        set_tts_enabled(not st["enabled"])
    return jsonify(get_tts_status())


@app.route("/api/tts/language", methods=["POST"])
def tts_language():
    body = request.get_json(silent=True) or {}
    lang = body.get("language", "en")
    try:
        return jsonify(set_tts_language(lang))
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400


@app.route("/api/tts/speak", methods=["POST"])
def tts_speak():
    body = request.get_json(silent=True) or {}
    lang = body.get("language")
    text = body.get("text") or build_test_phrase(lang)
    speak_async(text, lang)
    return jsonify({"ok": True, "text": text, "language": lang or get_tts_status().get("language")})


# ---------------------------------------------------------------------------
# SMS endpoints
# ---------------------------------------------------------------------------
@app.route("/api/sms/status")
def sms_status():
    return jsonify(get_sms_status())


@app.route("/api/sms/toggle", methods=["POST"])
def sms_toggle():
    body = request.get_json(silent=True) or {}
    if "enabled" in body:
        set_sms_enabled(bool(body["enabled"]))
    else:
        st = get_sms_status()
        set_sms_enabled(not st["enabled"])
    return jsonify(get_sms_status())


@app.route("/api/sms/test", methods=["POST"])
def sms_test():
    body = request.get_json(silent=True) or {}
    result = test_sms(body.get("message"))
    return jsonify(result)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    logger.info(
        "Starting on http://%s:%s", settings.FLASK_HOST, settings.FLASK_PORT
    )
    app.run(
        host=settings.FLASK_HOST,
        port=settings.FLASK_PORT,
        debug=settings.FLASK_DEBUG,
        use_reloader=False,  # avoid double simulator threads
        threaded=True,
    )
