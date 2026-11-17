"""Disaster monitoring dashboard for Andhra Pradesh and Telangana.

The application collects weather and station context, estimates disaster risk,
shows the current state on a dashboard, and raises alerts when conditions cross
configured thresholds. The server exposes REST endpoints and a live stream for
browser-based monitoring.
"""
from __future__ import annotations

import csv
import io
import json
import logging
import re
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

from flask import Flask, Response, jsonify, render_template, request, stream_with_context
from flask_cors import CORS

from alert_system import (
    broadcast,
    build_test_phrase,
    create_and_dispatch_alert,
    get_email_status,
    get_sms_status,
    get_tts_status,
    get_telegram_status,
    set_email_enabled,
    set_sms_enabled,
    set_tts_enabled,
    set_tts_language,
    send_email_message,
    send_sms_message,
    send_macos_notification,
    get_macos_notification_status,
    set_macos_notifications_enabled,
    set_telegram_enabled,
    speak_async,
    subscribe,
    test_email,
    test_sms,
    test_telegram,
    unsubscribe,
)
from config import settings
from database import (
    Alert,
    PredictionLog,
    Region,
    SensorReading,
    SessionLocal,
    SmsRecipient,
    init_db,
)
from disaster_data_generator import FEATURE_COLS, random_live_reading
from model_training import WEATHER_FEATURE_COLS, load_model, predict_disaster, train_and_save
from weather_service import get_current_weather_bulk, try_get_current_weather

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
CORS(app, resources={r"/api/*": {"origins": settings.CORS_ORIGINS}})

# ---------------------------------------------------------------------------
# Place catalog
def _load_places() -> list[dict]:
    places_path = settings.BASE_DIR / "data" / "ap_telangana_places.csv"
    if not places_path.exists():
        return []
    with places_path.open(newline="", encoding="utf-8") as handle:
        return [
            {
                "geoname_id": row["geoname_id"],
                "name": row["name"],
                "state": row["state"],
                "latitude": float(row["latitude"]),
                "longitude": float(row["longitude"]),
            }
            for row in csv.DictReader(handle)
        ]


PLACES = _load_places()

# ---------------------------------------------------------------------------
# Startup
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


def _website_sms_recipients(db) -> list[str]:
    return [row.phone_number for row in db.query(SmsRecipient).all()]


def process_reading(db, data: dict) -> dict:
    """Store a reading, score it, and publish any resulting alert."""
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
            sms_recipients=_website_sms_recipients(db),
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
            weather = try_get_current_weather(r.latitude, r.longitude)
            if settings.WEATHER_ENABLED and weather is None:
                logger.warning("Skipping %s: live weather is unavailable", r.name)
                _sim_stop.wait(settings.SIMULATOR_INTERVAL_SECONDS)
                continue
            packet = random_live_reading(region)
            if weather:
                packet.update({key: weather[key] for key in (
                    "temperature_c",
                    "humidity_pct",
                    "rainfall_mm",
                    "wind_speed_kmh",
                    "pressure_hpa",
                )})
            process_reading(db, packet)
        except Exception as exc:
            logger.warning("Simulator tick failed: %s", exc)
        finally:
            db.close()
        _sim_stop.wait(settings.SIMULATOR_INTERVAL_SECONDS)


if settings.SIMULATOR_ENABLED:
    _sim_thread = threading.Thread(target=_simulator_loop, daemon=True, name="simulator")
    _sim_thread.start()


def check_live_weather_alerts() -> int:
    """Evaluate current weather and dispatch newly detected severe conditions."""
    db = SessionLocal()
    dispatched = 0
    try:
        for region in db.query(Region).order_by(Region.state, Region.name).all():
            weather = try_get_current_weather(region.latitude, region.longitude)
            if not weather:
                continue
            prediction = predict_disaster({key: weather[key] for key in WEATHER_FEATURE_COLS})
            hazard = prediction["disaster_type"]
            if hazard not in ("flood", "cyclone", "wildfire") or prediction["risk_level"] not in ("high", "critical"):
                continue
            existing = db.query(Alert).filter(
                Alert.region_name == region.name,
                Alert.disaster_type == hazard,
                Alert.is_active.is_(True),
            ).first()
            create_and_dispatch_alert(
                db,
                Alert,
                region_name=region.name,
                disaster_type=hazard,
                risk_level=prediction["risk_level"],
                message=(
                    f"Live weather alert: {hazard.upper()} risk is "
                    f"{prediction['risk_level'].upper()} in {region.name}. "
                    f"{prediction.get('reason', '')}"
                ),
                sms_recipients=_website_sms_recipients(db),
            )
            if existing is None:
                dispatched += 1
    finally:
        db.close()
    return dispatched


def _live_alert_loop():
    logger.info("Live weather alert monitor started (interval=%ss)", settings.LIVE_ALERT_INTERVAL_SECONDS)
    while not _sim_stop.is_set():
        try:
            check_live_weather_alerts()
        except Exception as exc:
            logger.warning("Live alert check failed: %s", exc)
        _sim_stop.wait(settings.LIVE_ALERT_INTERVAL_SECONDS)


if settings.LIVE_ALERTS_ENABLED:
    threading.Thread(target=_live_alert_loop, daemon=True, name="live-alerts").start()


# ---------------------------------------------------------------------------
# Pages & static
# ---------------------------------------------------------------------------
@app.route("/")
def index():
    place_counts = {
        "Andhra Pradesh": sum(place["state"] == "Andhra Pradesh" for place in PLACES),
        "Telangana": sum(place["state"] == "Telangana" for place in PLACES),
        "total": len(PLACES),
    }
    place_coverage = {key: f"{value:,}" for key, value in place_counts.items()}
    return render_template(
        "index.html",
        place_coverage=place_coverage,
        google_maps_api_key=settings.GOOGLE_MAPS_API_KEY,
    )


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


@app.route("/api/places")
def list_places():
    """Search the complete AP and Telangana populated-place catalog."""
    query = request.args.get("q", "").strip().casefold()
    state = request.args.get("state", "").strip().casefold()
    try:
        limit = min(max(int(request.args.get("limit", "100")), 1), 500)
        offset = max(int(request.args.get("offset", "0")), 0)
    except ValueError:
        return jsonify({"error": "limit and offset must be integers"}), 400
    matches = [
        place for place in PLACES
        if (not query or query in place["name"].casefold())
        and (not state or state in place["state"].casefold())
    ]
    return jsonify({
        "total": len(matches),
        "offset": offset,
        "limit": limit,
        "places": matches[offset:offset + limit],
    })


@app.route("/api/place-map")
def place_map():
    """Return the complete lightweight place catalog for map rendering."""
    return jsonify(PLACES)


@app.route("/api/weather")
def current_weather():
    """Fetch current weather for a configured region or supplied coordinates."""
    db = SessionLocal()
    try:
        region_name = request.args.get("region")
        region = db.query(Region).filter(Region.name == region_name).first() if region_name else None
        try:
            place_id = request.args.get("place_id")
            place = next((item for item in PLACES if item["geoname_id"] == place_id), None) if place_id else None
            if place_id and place is None:
                return jsonify({"error": "Unknown place_id"}), 404
            if "latitude" in request.args and "longitude" in request.args:
                latitude = float(request.args["latitude"])
                longitude = float(request.args["longitude"])
            elif place:
                latitude, longitude = place["latitude"], place["longitude"]
            elif region:
                latitude, longitude = region.latitude, region.longitude
            else:
                raise ValueError
        except (KeyError, AttributeError, TypeError, ValueError):
            return jsonify({"error": "Provide a valid region or latitude and longitude"}), 400
        weather = try_get_current_weather(latitude, longitude)
        if weather is None:
            return jsonify({"error": "Live weather is unavailable"}), 503
        return jsonify({"place": place, "latitude": latitude, "longitude": longitude, **weather})
    finally:
        db.close()


@app.route("/api/live-alerts/check", methods=["POST"])
def live_alert_check():
    """Run one immediate live-weather alert check."""
    return jsonify({"dispatched": check_live_weather_alerts()})


@app.route("/api/place-predictions")
def place_predictions():
    """Predict from the latest stored sensor data, never from a generated profile."""
    place_query = request.args.get("q", "").strip().casefold()
    state = request.args.get("state", "").strip().casefold()
    if place_query:
        try:
            limit = min(max(int(request.args.get("limit", "100")), 1), 100)
            offset = max(int(request.args.get("offset", "0")), 0)
        except ValueError:
            return jsonify({"error": "limit and offset must be integers"}), 400
        filtered = [
            place for place in PLACES
            if place_query in place["name"].casefold()
            and (not state or state == place["state"].casefold())
        ]
        total = len(filtered)
        matches = filtered[offset:offset + limit]
    else:
        try:
            limit = min(max(int(request.args.get("limit", "100")), 1), 100)
            offset = max(int(request.args.get("offset", "0")), 0)
        except ValueError:
            return jsonify({"error": "limit and offset must be integers"}), 400
        filtered = [place for place in PLACES if not state or state == place["state"].casefold()]
        matches = filtered[offset:offset + limit]

    weather_rows = get_current_weather_bulk([
        (place["latitude"], place["longitude"]) for place in matches
    ])
    results = []
    for place, weather in zip(matches, weather_rows):
        packet = {key: weather[key] for key in WEATHER_FEATURE_COLS} if weather else None
        prediction = predict_disaster(packet) if packet else {
            "disaster_type": "unavailable",
            "risk_level": "unknown",
            "confidence": 0,
            "probabilities": {},
            "reason": "Live weather is unavailable for this location.",
        }
        results.append({
            "region_name": place["name"],
            "state": place["state"],
            "station_id": f"GN-{place['geoname_id']}",
            "latitude": place["latitude"],
            "longitude": place["longitude"],
            "weather": packet or {},
            "weather_source": "live weather" if weather else "live weather required",
            "weather_provider": weather.get("source") if weather else None,
            "is_live_weather": bool(weather and weather.get("is_live")),
            "observed_at": weather.get("observed_at") if weather else None,
            "prediction": prediction,
        })
    if place_query:
        return jsonify({"total": total, "offset": offset, "limit": len(matches), "places": results})
    state = request.args.get("state", "").strip().casefold()
    total = sum(1 for place in PLACES if not state or state == place["state"].casefold())
    return jsonify({"total": total, "offset": offset, "limit": len(matches), "places": results})

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
        q = db.query(Alert).order_by(Alert.created_at.desc())
        if active_only:
            cutoff = datetime.utcnow() - timedelta(seconds=settings.ALERT_MAX_AGE_SECONDS)
            q = q.filter(
                Alert.is_active.is_(True),
                Alert.created_at >= cutoff,
                Alert.disaster_type.in_(("flood", "cyclone", "wildfire")),
            )
        q = q.limit(50)
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


@app.route("/api/sms/demo", methods=["POST"])
def sms_demo():
    body = request.get_json(silent=True) or {}
    message = str(body.get("message", "")).strip()
    if not message:
        return jsonify({"error": "Enter a test message first."}), 400
    db = SessionLocal()
    try:
        recipients = _website_sms_recipients(db)
    finally:
        db.close()
    if not recipients:
        return jsonify({"error": "Add at least one saved recipient first."}), 400
    result = send_sms_message(message, recipients)
    return jsonify({"recipients": len(recipients), "message": result})


@app.route("/api/telegram/status")
def telegram_status():
    return jsonify(get_telegram_status())


@app.route("/api/telegram/toggle", methods=["POST"])
def telegram_toggle():
    body = request.get_json(silent=True) or {}
    set_telegram_enabled(bool(body["enabled"]) if "enabled" in body else not get_telegram_status()["enabled"])
    return jsonify(get_telegram_status())


@app.route("/api/telegram/test", methods=["POST"])
def telegram_test():
    body = request.get_json(silent=True) or {}
    return jsonify(test_telegram(body.get("message")))


@app.route("/api/email/status")
def email_status():
    return jsonify(get_email_status())


@app.route("/api/email/toggle", methods=["POST"])
def email_toggle():
    body = request.get_json(silent=True) or {}
    set_email_enabled(bool(body["enabled"]) if "enabled" in body else not get_email_status()["enabled"])
    return jsonify(get_email_status())


@app.route("/api/email/test", methods=["POST"])
def email_test():
    body = request.get_json(silent=True) or {}
    return jsonify(test_email(body.get("message")))


@app.route("/api/macos-notification/test", methods=["POST"])
def macos_notification_test():
    body = request.get_json(silent=True) or {}
    return jsonify(send_macos_notification(
        "Disaster Prediction System",
        body.get("message") or "Offline macOS notification test",
    ))


@app.route("/api/macos-notification/status")
def macos_notification_status():
    return jsonify(get_macos_notification_status())


@app.route("/api/macos-notification/toggle", methods=["POST"])
def macos_notification_toggle():
    body = request.get_json(silent=True) or {}
    current = get_macos_notification_status()["enabled"]
    set_macos_notifications_enabled(bool(body["enabled"]) if "enabled" in body else not current)
    return jsonify(get_macos_notification_status())


def _normalize_phone(value: str) -> str | None:
    value = value.strip()
    if not value or re.search(r"phone|mobile|number", value, re.IGNORECASE):
        return None
    compact = re.sub(r"[\s().-]", "", value)
    if compact.startswith("0") and len(compact) == 11:
        compact = compact[1:]
    if compact.isdigit() and len(compact) == 10:
        compact = "+91" + compact
    elif compact.isdigit() and len(compact) == 12 and compact.startswith("91"):
        compact = "+" + compact
    if not re.fullmatch(r"\+[1-9]\d{9,14}", compact):
        return None
    return compact


@app.route("/api/sms/recipients", methods=["GET"])
def sms_recipients():
    db = SessionLocal()
    try:
        rows = db.query(SmsRecipient).order_by(SmsRecipient.phone_number).all()
        return jsonify({"recipients": [row.phone_number for row in rows]})
    finally:
        db.close()


@app.route("/api/sms/recipients", methods=["POST"])
def add_sms_recipient():
    body = request.get_json(silent=True) or {}
    number = _normalize_phone(str(body.get("phone_number", "")))
    if not number:
        return jsonify({"error": "Enter a valid mobile number."}), 400
    db = SessionLocal()
    try:
        if not db.query(SmsRecipient).filter(SmsRecipient.phone_number == number).first():
            db.add(SmsRecipient(phone_number=number))
            db.commit()
        return jsonify({"phone_number": number})
    finally:
        db.close()


@app.route("/api/sms/recipients/<path:phone_number>", methods=["DELETE"])
def remove_sms_recipient(phone_number):
    number = _normalize_phone(phone_number)
    if not number:
        return jsonify({"error": "Invalid mobile number."}), 400
    db = SessionLocal()
    try:
        row = db.query(SmsRecipient).filter(SmsRecipient.phone_number == number).first()
        if row:
            db.delete(row)
            db.commit()
        return jsonify({"removed": number})
    finally:
        db.close()


def _latest_sms_alert(db):
    return (
        db.query(Alert)
        .filter(Alert.is_active.is_(True), Alert.disaster_type != "none")
        .order_by(Alert.created_at.desc())
        .first()
    )


@app.route("/api/sms/preview")
def sms_preview():
    db = SessionLocal()
    try:
        alert = _latest_sms_alert(db)
        if not alert:
            return jsonify({"message": None, "error": "No active disaster alert."}), 404
        message = f"[Disaster Alert] {alert.disaster_type.upper()} risk is {alert.risk_level.upper()} in {alert.region_name}."
        return jsonify({"message": message, "alert_id": alert.id})
    finally:
        db.close()


@app.route("/api/sms/upload", methods=["POST"])
def sms_upload():
    uploaded = request.files.get("file")
    if uploaded and uploaded.filename:
        try:
            text = uploaded.read().decode("utf-8-sig")
        except UnicodeDecodeError:
            return jsonify({"error": "The uploaded file must be UTF-8 text."}), 400
    else:
        text = request.form.get("numbers", "")
    if not text.strip():
        return jsonify({"error": "Enter at least one mobile number."}), 400

    numbers = []
    for row in csv.reader(io.StringIO(text)):
        for cell in row:
            number = _normalize_phone(cell)
            if number and number not in numbers:
                numbers.append(number)
    if not numbers:
        return jsonify({"error": "No valid mobile numbers found."}), 400
    if len(numbers) > 5000:
        return jsonify({"error": "Send up to 5,000 mobile numbers at a time."}), 400

    db = SessionLocal()
    try:
        alert = _latest_sms_alert(db)
        if not alert:
            return jsonify({"error": "No active disaster alert is available to send."}), 409
        message = f"[Disaster Alert] {alert.disaster_type.upper()} risk is {alert.risk_level.upper()} in {alert.region_name}."
        existing = {
            row.phone_number
            for row in db.query(SmsRecipient).filter(SmsRecipient.phone_number.in_(numbers)).all()
        }
        for number in numbers:
            if number not in existing:
                db.add(SmsRecipient(phone_number=number))
        db.commit()
    finally:
        db.close()

    result = send_sms_message(message, numbers)
    return jsonify({"uploaded": len(numbers), "alert_message": message, "message": result})


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
