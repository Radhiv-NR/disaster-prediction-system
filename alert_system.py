"""Alerts: SSE broadcaster, multilingual TTS (en/hi/te), Twilio SMS."""
from __future__ import annotations

import json
import logging
import queue
import threading
import time
from typing import Any

import requests

from config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# SSE broadcaster
# ---------------------------------------------------------------------------
_sse_clients: list[queue.Queue] = []
_sse_lock = threading.Lock()


def subscribe() -> queue.Queue:
    q: queue.Queue = queue.Queue(maxsize=64)
    with _sse_lock:
        _sse_clients.append(q)
    return q


def unsubscribe(q: queue.Queue) -> None:
    with _sse_lock:
        if q in _sse_clients:
            _sse_clients.remove(q)


def broadcast(event: str, data: dict) -> None:
    payload = f"event: {event}\ndata: {json.dumps(data)}\n\n"
    dead: list[queue.Queue] = []
    with _sse_lock:
        clients = list(_sse_clients)
    for q in clients:
        try:
            q.put_nowait(payload)
        except queue.Full:
            dead.append(q)
    for q in dead:
        unsubscribe(q)


# ---------------------------------------------------------------------------
# Multilingual TTS (pyttsx3)
# ---------------------------------------------------------------------------
_tts_enabled = settings.TTS_ENABLED
_tts_language = settings.TTS_LANGUAGE  # en | hi | te
_tts_queue: queue.Queue = queue.Queue()
_tts_ready = False
_tts_lock = threading.Lock()

# Complete offline phrase packs — English, Hindi, Telugu (no translation API)
SUPPORTED_LANGUAGES = ("en", "hi", "te")

PHRASES = {
    "en": {
        "template": "Alert. {disaster} risk is {risk} in {region}, Andhra Pradesh Telangana region.",
        "template_short": "Alert. {disaster} risk is {risk} in {region}.",
        "disaster": {
            "flood": "flood",
            "cyclone": "cyclone",
            "earthquake": "earthquake",
            "wildfire": "wildfire",
            "none": "no disaster",
        },
        "risk": {
            "none": "none",
            "low": "low",
            "medium": "medium",
            "high": "high",
            "critical": "critical",
        },
        "test": "Disaster prediction system voice test in English.",
    },
    "hi": {
        "template": "चेतावनी. {region} में {disaster} का खतरा {risk} स्तर पर है. कृपया सुरक्षित रहें.",
        "template_short": "चेतावनी. {region} में {disaster} का खतरा {risk} स्तर पर है.",
        "disaster": {
            "flood": "बाढ़",
            "cyclone": "चक्रवात",
            "earthquake": "भूकंप",
            "wildfire": "जंगल की आग",
            "none": "कोई आपदा नहीं",
        },
        "risk": {
            "none": "नगण्य",
            "low": "कम",
            "medium": "मध्यम",
            "high": "उच्च",
            "critical": "अति गंभीर",
        },
        "test": "आपदा पूर्वानुमान प्रणाली हिंदी में आवाज़ परीक्षण.",
    },
    "te": {
        "template": "హెచ్చరిక. {region}లో {disaster} ప్రమాదం {risk} స్థాయిలో ఉంది. దయచేసి సురక్షితంగా ఉండండి.",
        "template_short": "హెచ్చరిక. {region}లో {disaster} ప్రమాదం {risk} స్థాయిలో ఉంది.",
        "disaster": {
            "flood": "వరద",
            "cyclone": "తుఫాను",
            "earthquake": "భూకంపం",
            "wildfire": "అడవి మంటలు",
            "none": "ప్రమాదం లేదు",
        },
        "risk": {
            "none": "లేదు",
            "low": "తక్కువ",
            "medium": "మధ్యస్థ",
            "high": "ఎక్కువ",
            "critical": "అత్యంత తీవ్రమైన",
        },
        "test": "విపత్తు అంచనా వ్యవస్థ తెలుగులో వాయిస్ పరీక్ష.",
    },
}

RISK_RANK = {"none": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}


def build_alert_phrase(
    disaster: str,
    risk: str,
    region: str,
    lang: str | None = None,
    *,
    short: bool = True,
) -> str:
    """Build a spoken alert in English, Hindi, or Telugu."""
    lang = (lang or _tts_language or "en").lower()
    if lang not in PHRASES:
        lang = "en"
    p = PHRASES[lang]
    key = "template_short" if short else "template"
    return p[key].format(
        disaster=p["disaster"].get(disaster, disaster),
        risk=p["risk"].get(risk, risk),
        region=region,
    )


def build_test_phrase(lang: str | None = None) -> str:
    lang = (lang or _tts_language or "en").lower()
    if lang not in PHRASES:
        lang = "en"
    return PHRASES[lang]["test"]


def _pick_voice(engine, lang: str):
    """Match macOS / system voices for en, hi, te."""
    try:
        voices = engine.getProperty("voices") or []
    except Exception:
        return
    lang = lang.lower()
    # Ordered preference lists (substring match against voice id/name/languages)
    prefer = {
        "en": ["en_in", "en-in", "en_us", "en-us", "en_gb", "en-gb", "en_", "english", "samantha", "alex", "rishi", "veena"],
        "hi": ["hi_in", "hi-in", "hi_", "hindi", "lekha", "neel"],
        "te": ["te_in", "te-in", "te_", "telugu"],
    }.get(lang, ["en_"])
    for tok in prefer:
        for v in voices:
            blob = f"{getattr(v, 'id', '')} {getattr(v, 'name', '')} {getattr(v, 'languages', '')}".lower()
            if tok in blob:
                try:
                    engine.setProperty("voice", v.id)
                    logger.info("TTS voice selected for %s: %s", lang, getattr(v, "name", v.id))
                    return
                except Exception:
                    continue
    if lang != "en":
        logger.info(
            "No %s system voice found — using default voice. "
            "On macOS add one via System Settings → Accessibility → Spoken Content.",
            lang,
        )


def _tts_worker():
    global _tts_ready
    try:
        import pyttsx3

        engine = pyttsx3.init()
        engine.setProperty("rate", 165)
        _tts_ready = True
        logger.info("TTS engine ready")
        while True:
            item = _tts_queue.get()
            if item is None:
                break
            text, lang = item
            try:
                _pick_voice(engine, lang)
                engine.say(text)
                engine.runAndWait()
            except Exception as exc:
                logger.warning("TTS speak failed: %s", exc)
    except Exception as exc:
        logger.warning("TTS unavailable (%s) — voice alerts disabled", exc)
        _tts_ready = False


_tts_thread = threading.Thread(target=_tts_worker, daemon=True, name="tts-worker")
_tts_thread.start()


def set_tts_enabled(enabled: bool) -> None:
    global _tts_enabled
    _tts_enabled = bool(enabled)


def get_tts_status() -> dict:
    return {
        "enabled": _tts_enabled,
        "ready": _tts_ready,
        "language": _tts_language,
        "supported": list(SUPPORTED_LANGUAGES),
        "min_risk": settings.TTS_MIN_RISK,
    }


def set_tts_language(lang: str) -> dict:
    global _tts_language
    lang = lang.lower().strip()
    if lang not in SUPPORTED_LANGUAGES:
        raise ValueError(
            f"Unsupported language: {lang}. Use en (English), hi (Hindi), or te (Telugu)."
        )
    _tts_language = lang
    return get_tts_status()


def speak_async(text: str, lang: str | None = None) -> None:
    if not _tts_enabled:
        return
    _tts_queue.put((text, (lang or _tts_language)))


def maybe_speak_alert(disaster: str, risk: str, region: str) -> None:
    if not _tts_enabled:
        return
    if RISK_RANK.get(risk, 0) < RISK_RANK.get(settings.TTS_MIN_RISK, 3):
        return
    phrase = build_alert_phrase(disaster, risk, region)
    speak_async(phrase)


# ---------------------------------------------------------------------------
# SMS via Twilio REST (requests only — no twilio SDK)
# ---------------------------------------------------------------------------
_sms_enabled = settings.SMS_ENABLED


def set_sms_enabled(enabled: bool) -> None:
    global _sms_enabled
    _sms_enabled = bool(enabled)


def get_sms_status() -> dict:
    configured = bool(
        settings.TWILIO_ACCOUNT_SID
        and settings.TWILIO_AUTH_TOKEN
        and settings.TWILIO_FROM_NUMBER
        and settings.SMS_TO_NUMBERS
    )
    return {
        "enabled": _sms_enabled,
        "configured": configured,
        "min_risk": settings.SMS_MIN_RISK,
        "recipients": len(settings.SMS_TO_NUMBERS),
    }


def _send_sms_sync(body: str) -> dict:
    status = get_sms_status()
    if not status["enabled"]:
        return {"sent": 0, "reason": "disabled"}
    if not status["configured"]:
        logger.warning("SMS enabled but Twilio credentials / recipients missing — skip")
        return {"sent": 0, "reason": "not_configured"}

    url = (
        f"https://api.twilio.com/2010-04-01/Accounts/"
        f"{settings.TWILIO_ACCOUNT_SID}/Messages.json"
    )
    sent = 0
    errors = []
    for to in settings.SMS_TO_NUMBERS:
        try:
            resp = requests.post(
                url,
                data={"From": settings.TWILIO_FROM_NUMBER, "To": to, "Body": body},
                auth=(settings.TWILIO_ACCOUNT_SID, settings.TWILIO_AUTH_TOKEN),
                timeout=15,
            )
            if resp.status_code in (200, 201):
                sent += 1
            else:
                errors.append({"to": to, "status": resp.status_code, "body": resp.text[:200]})
        except Exception as exc:
            errors.append({"to": to, "error": str(exc)})
    return {"sent": sent, "errors": errors}


def send_sms_alert(disaster: str, risk: str, region: str) -> None:
    if not _sms_enabled:
        return
    if RISK_RANK.get(risk, 0) < RISK_RANK.get(settings.SMS_MIN_RISK, 4):
        return
    # SMS stays English for carrier reliability
    body = f"[Disaster Alert] {disaster.upper()} risk is {risk.upper()} in {region}."

    def _run():
        result = _send_sms_sync(body)
        logger.info("SMS alert result: %s", result)

    threading.Thread(target=_run, daemon=True, name="sms-send").start()


def test_sms(message: str | None = None) -> dict:
    body = message or "Disaster Prediction System — SMS test message."
    return _send_sms_sync(body)


# ---------------------------------------------------------------------------
# Unified alert creation helper
# ---------------------------------------------------------------------------
def create_and_dispatch_alert(
    db,
    AlertModel,
    region_name: str,
    disaster_type: str,
    risk_level: str,
    message: str | None = None,
) -> Any:
    """Persist alert, broadcast over SSE, speak, and SMS."""
    msg = message or build_alert_phrase(disaster_type, risk_level, region_name, "en")
    alert = AlertModel(
        region_name=region_name,
        disaster_type=disaster_type,
        risk_level=risk_level,
        message=msg,
        is_active=True,
    )
    db.add(alert)
    db.commit()
    db.refresh(alert)

    payload = {
        "id": alert.id,
        "region_name": region_name,
        "disaster_type": disaster_type,
        "risk_level": risk_level,
        "message": msg,
        "created_at": alert.created_at.isoformat() if alert.created_at else None,
    }
    broadcast("alert", payload)
    maybe_speak_alert(disaster_type, risk_level, region_name)
    send_sms_alert(disaster_type, risk_level, region_name)
    return alert
