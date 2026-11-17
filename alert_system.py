"""Alert delivery for the dashboard, voice, desktop, SMS, email, and Telegram."""
from __future__ import annotations

import json
import logging
import queue
import re
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import requests

from config import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# SSE broadcaster
# ---------------------------------------------------------------------------
# Each connected browser gets its own queue so a slow client cannot block the
# simulator or the other subscribers.
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

# Keep the spoken phrases local so alerts still work without a translation API.
SUPPORTED_LANGUAGES = ("en", "hi", "te")

_macos_voice_cache: dict[str, str | None] = {}

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
SMS_MESSAGE_LIMIT = 1600


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


def _macos_voice_for(lang: str) -> str | None:
    """Find an installed macOS voice for the requested language."""
    lang = lang.lower()
    if lang in _macos_voice_cache:
        return _macos_voice_cache[lang]

    preferred_locales = {
        "en": ("en_IN", "en_US", "en_GB"),
        "hi": ("hi_IN",),
        "te": ("te_IN",),
    }.get(lang, ("en_US",))
    try:
        result = subprocess.run(
            ["say", "-v", "?"],
            capture_output=True,
            text=True,
            check=False,
        )
        voices = [
            (match.group(1), match.group(2))
            for line in result.stdout.splitlines()
            if (match := re.match(r"^\s*(\S+)\s+([a-z]{2}_[A-Z]{2})\b", line))
        ]
    except Exception as exc:
        logger.warning("Unable to inspect macOS speech voices: %s", exc)
        _macos_voice_cache[lang] = None
        return None

    for locale in preferred_locales:
        for voice_name, voice_locale in voices:
            if voice_locale == locale:
                _macos_voice_cache[lang] = voice_name
                return voice_name

    _macos_voice_cache[lang] = None
    if lang != "en":
        logger.info(
            "No macOS voice found for %s; using the system default voice. "
            "Install a matching voice in Accessibility > Spoken Content.",
            lang,
        )
    return None


def _tts_worker():
    global _tts_ready
    if sys.platform == "darwin":
        _tts_ready = True
        logger.info("TTS engine ready (macOS say)")
        while True:
            item = _tts_queue.get()
            if item is None:
                break
            text, lang = item
            try:
                voice = _macos_voice_for(lang)
                command = ["say"]
                if voice:
                    command.extend(["-v", voice])
                command.append(text)
                subprocess.run(command, check=False)
            except Exception as exc:
                logger.warning("TTS speak failed: %s", exc)
        return

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
# Offline macOS Notification Center alerts
# ---------------------------------------------------------------------------
def _macos_notification_text(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")


def send_macos_notification(title: str, message: str) -> dict:
    if sys.platform != "darwin":
        return {"sent": 0, "reason": "macos_only"}
    if not settings.MACOS_NOTIFICATIONS_ENABLED:
        return {"sent": 0, "reason": "disabled"}
    script = (
        f'display notification "{_macos_notification_text(message)}" '
        f'with title "{_macos_notification_text(title)}"'
    )
    try:
        result = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, check=False)
    except OSError as exc:
        return {"sent": 0, "reason": "osascript_unavailable", "error": str(exc)}
    if result.returncode:
        return {"sent": 0, "reason": "notification_failed", "error": result.stderr.strip()}
    return {"sent": 1}


def set_macos_notifications_enabled(enabled: bool) -> None:
    settings.MACOS_NOTIFICATIONS_ENABLED = bool(enabled)


def get_macos_notification_status() -> dict:
    return {
        "enabled": settings.MACOS_NOTIFICATIONS_ENABLED,
        "ready": sys.platform == "darwin",
        "provider": "macos_notification_center",
        "min_risk": settings.MACOS_NOTIFICATIONS_MIN_RISK,
    }


def send_macos_alert(disaster: str, risk: str, region: str) -> None:
    if RISK_RANK.get(risk, 0) < RISK_RANK.get(settings.MACOS_NOTIFICATIONS_MIN_RISK, 3):
        return
    result = send_macos_notification(
        "Disaster Alert", f"{disaster.upper()} risk is {risk.upper()} in {region}."
    )
    logger.info("macOS notification result: %s", result)


# ---------------------------------------------------------------------------
# SIM7600 GSM SMS
# ---------------------------------------------------------------------------
_sms_enabled = settings.SMS_ENABLED or settings.GSM_ENABLED


def _gsm_port() -> str | None:
    configured = settings.GSM_PORT.strip()
    if configured and Path(configured).exists():
        return configured
    patterns = (configured,) if "*" in configured else ()
    patterns += ("/dev/cu.usbmodem*", "/dev/cu.SLAB*", "/dev/cu.usbserial*")
    for pattern in patterns:
        matches = sorted(Path("/dev").glob(pattern.removeprefix("/dev/")))
        if matches:
            return str(matches[0])
    return None


def _gsm_ports() -> list[str]:
    ports: set[str] = set()
    for pattern in ("/dev/cu.usbmodem*", "/dev/cu.SLAB*", "/dev/cu.usbserial*"):
        ports.update(str(path) for path in Path("/dev").glob(pattern.removeprefix("/dev/")))
    return sorted(ports)


def set_sms_enabled(enabled: bool) -> None:
    global _sms_enabled
    _sms_enabled = bool(enabled)


def get_sms_status() -> dict:
    port = _gsm_port()
    gsm_configured = bool(port and settings.GSM_TO_NUMBERS)
    return {
        "enabled": _sms_enabled,
        "configured": gsm_configured,
        "ready": bool(settings.GSM_ENABLED and gsm_configured),
        "port": port,
        "available_ports": _gsm_ports(),
        "provider": "sim7600",
        "min_risk": settings.SMS_MIN_RISK,
        "recipients": len(settings.GSM_TO_NUMBERS),
    }


def _send_gsm_sms_sync(body: str, recipients: list[str] | None = None) -> dict:
    """Send SMS through a SIM7600 using its serial AT command interface."""
    recipients = recipients if recipients is not None else settings.GSM_TO_NUMBERS
    port = _gsm_port()
    if not port or not recipients:
        return {"sent": 0, "reason": "not_configured"}
    try:
        import serial
    except ImportError:
        return {"sent": 0, "reason": "pyserial_not_installed"}

    sent = 0
    errors = []
    try:
        with serial.Serial(port, settings.GSM_BAUDRATE, timeout=8) as modem:
            modem.write(b"AT\r")
            if b"OK" not in modem.read_until(b"OK"):
                return {"sent": 0, "reason": "modem_not_responding"}
            modem.write(b"AT+CMGF=1\r")
            modem.read_until(b"OK")
            for to in recipients:
                try:
                    modem.reset_input_buffer()
                    modem.write(f'AT+CMGS="{to}"\r'.encode())
                    if b">" not in modem.read_until(b">"):
                        errors.append({"to": to, "error": "modem did not accept message"})
                        continue
                    modem.write(body.encode("utf-8") + b"\x1a")
                    response = modem.read_until(b"OK")
                    if b"OK" in response:
                        sent += 1
                    else:
                        errors.append({"to": to, "error": response.decode(errors="replace")[-200:]})
                except Exception as exc:
                    errors.append({"to": to, "error": str(exc)})
    except Exception as exc:
        return {"sent": 0, "reason": "modem_connection_failed", "error": str(exc)}
    return {"sent": sent, "errors": errors}


def _send_sms_sync(body: str, recipients: list[str] | None = None) -> dict:
    status = get_sms_status()
    if not status["enabled"]:
        return {"sent": 0, "reason": "disabled"}
    if not _gsm_port():
        return {"sent": 0, "reason": "modem_not_connected"}
    if not (recipients or settings.GSM_TO_NUMBERS):
        logger.warning("SMS enabled but configured provider / recipients missing — skip")
        return {"sent": 0, "reason": "not_configured"}

    if not settings.GSM_ENABLED:
        return {"sent": 0, "reason": "gsm_disabled"}
    return _send_gsm_sms_sync(body, recipients)


def send_sms_message(body: str, recipients: list[str]) -> dict:
    """Send a user-supplied message to a validated recipient list."""
    body = (body or "").strip()
    if not body:
        return {"sent": 0, "reason": "message_required"}
    if len(body) > SMS_MESSAGE_LIMIT:
        return {"sent": 0, "reason": "message_too_long"}
    return _send_sms_sync(body, recipients)


def send_sms_alert(
    disaster: str,
    risk: str,
    region: str,
    recipients: list[str] | None = None,
) -> None:
    if not _sms_enabled:
        return
    if RISK_RANK.get(risk, 0) < RISK_RANK.get(settings.SMS_MIN_RISK, 4):
        return
    # SMS stays English for carrier reliability
    body = f"[Disaster Alert] {disaster.upper()} risk is {risk.upper()} in {region}."

    def _run():
        result = _send_sms_sync(body, recipients)
        logger.info("SMS alert result: %s", result)

    threading.Thread(target=_run, daemon=True, name="sms-send").start()


def test_sms(message: str | None = None) -> dict:
    body = message or "Disaster Prediction System - SIM7600 SMS test message."
    return _send_sms_sync(body)


# ---------------------------------------------------------------------------
# Telegram alerts (free Bot API)
# ---------------------------------------------------------------------------
_telegram_enabled = settings.TELEGRAM_ENABLED


def set_telegram_enabled(enabled: bool) -> None:
    global _telegram_enabled
    _telegram_enabled = bool(enabled)


def get_telegram_status() -> dict:
    configured = bool(settings.TELEGRAM_BOT_TOKEN and settings.TELEGRAM_CHAT_IDS)
    return {
        "enabled": _telegram_enabled,
        "configured": configured,
        "ready": bool(_telegram_enabled and configured),
        "provider": "telegram",
        "min_risk": settings.TELEGRAM_MIN_RISK,
        "recipients": len(settings.TELEGRAM_CHAT_IDS),
    }


def _send_telegram_sync(body: str, chat_ids: list[str] | None = None) -> dict:
    chat_ids = chat_ids if chat_ids is not None else settings.TELEGRAM_CHAT_IDS
    if not settings.TELEGRAM_BOT_TOKEN or not chat_ids:
        return {"sent": 0, "reason": "not_configured"}
    url = f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/sendMessage"
    sent = 0
    errors = []
    for chat_id in chat_ids:
        try:
            response = requests.post(
                url,
                json={"chat_id": chat_id, "text": body},
                timeout=settings.TELEGRAM_API_TIMEOUT_SECONDS,
            )
            if response.ok and response.json().get("ok"):
                sent += 1
            else:
                errors.append({"chat_id": chat_id, "error": response.text[-200:]})
        except requests.RequestException as exc:
            errors.append({"chat_id": chat_id, "error": str(exc)})
    result = {"sent": sent, "errors": errors}
    if not sent and errors:
        result["reason"] = "telegram_send_failed"
    return result


def send_telegram_message(body: str, chat_ids: list[str] | None = None) -> dict:
    body = (body or "").strip()
    if not body:
        return {"sent": 0, "reason": "message_required"}
    if not _telegram_enabled:
        return {"sent": 0, "reason": "disabled"}
    return _send_telegram_sync(body, chat_ids)


def send_telegram_alert(disaster: str, risk: str, region: str) -> None:
    if not _telegram_enabled:
        return
    if RISK_RANK.get(risk, 0) < RISK_RANK.get(settings.TELEGRAM_MIN_RISK, 3):
        return
    body = f"[Disaster Alert] {disaster.upper()} risk is {risk.upper()} in {region}."

    def _run():
        result = _send_telegram_sync(body)
        logger.info("Telegram alert result: %s", result)

    threading.Thread(target=_run, daemon=True, name="telegram-send").start()


def test_telegram(message: str | None = None) -> dict:
    return send_telegram_message(message or "Disaster Prediction System - Telegram test message.")


# ---------------------------------------------------------------------------
# SMTP email alerts
# ---------------------------------------------------------------------------
_email_enabled: bool | None = None


def _email_is_enabled() -> bool:
    return settings.EMAIL_ENABLED if _email_enabled is None else _email_enabled


def set_email_enabled(enabled: bool) -> None:
    global _email_enabled
    _email_enabled = bool(enabled)


def get_email_status() -> dict:
    configured = bool(settings.EMAIL_FROM and settings.EMAIL_TO)
    return {
        "enabled": _email_is_enabled(),
        "configured": configured,
        "ready": bool(_email_enabled and configured and settings.SMTP_HOST),
        "provider": "smtp",
        "min_risk": settings.EMAIL_MIN_RISK,
        "recipients": len(settings.EMAIL_TO),
    }


def _send_email_sync(
    body: str,
    recipients: list[str] | None = None,
    subject: str = "Disaster Alert",
) -> dict:
    recipients = recipients if recipients is not None else settings.EMAIL_TO
    if not _email_is_enabled():
        return {"sent": 0, "reason": "disabled"}
    if not settings.SMTP_HOST or not settings.EMAIL_FROM or not recipients:
        return {"sent": 0, "reason": "not_configured"}

    try:
        import smtplib
        from email.message import EmailMessage
    except ImportError as exc:
        return {"sent": 0, "reason": "email_lib_unavailable", "error": str(exc)}

    msg = EmailMessage()
    msg["From"] = settings.EMAIL_FROM
    msg["To"] = ", ".join(recipients)
    msg["Subject"] = subject
    msg.set_content(body)

    try:
        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=settings.SMTP_TIMEOUT_SECONDS) as server:
            if settings.SMTP_USE_TLS:
                server.starttls()
            if settings.SMTP_USERNAME:
                server.login(settings.SMTP_USERNAME, settings.SMTP_PASSWORD)
            server.send_message(msg)
        return {"sent": len(recipients)}
    except Exception as exc:
        return {"sent": 0, "reason": "smtp_send_failed", "error": str(exc)}


def send_email_message(body: str, recipients: list[str] | None = None) -> dict:
    body = (body or "").strip()
    if not body:
        return {"sent": 0, "reason": "message_required"}
    return _send_email_sync(body, recipients)


def send_email_alert(
    disaster: str,
    risk: str,
    region: str,
    recipients: list[str] | None = None,
) -> dict:
    if not _email_is_enabled():
        return {"sent": 0, "reason": "disabled"}
    if RISK_RANK.get(risk, 0) < RISK_RANK.get(settings.EMAIL_MIN_RISK, 3):
        return {"sent": 0, "reason": "below_minimum_risk"}
    body = f"[Disaster Alert] {disaster.upper()} risk is {risk.upper()} in {region}."
    subject = f"Disaster Alert: {disaster} risk is {risk.upper()} in {region}"
    result = _send_email_sync(body, recipients, subject)
    logger.info("Email alert result: %s", result)
    return result


def test_email(message: str | None = None) -> dict:
    return send_email_message(message or "Disaster Prediction System - Email test message.")


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
    sms_recipients: list[str] | None = None,
) -> Any:
    """Persist alert, broadcast over SSE, speak, and SMS."""
    if disaster_type not in ("flood", "cyclone", "wildfire"):
        logger.info("Skipping unsupported weather alert type: %s", disaster_type)
        return None
    existing = (
        db.query(AlertModel)
        .filter(
            AlertModel.region_name == region_name,
            AlertModel.disaster_type == disaster_type,
            AlertModel.is_active.is_(True),
            AlertModel.created_at >= datetime.utcnow() - timedelta(
                seconds=settings.ALERT_MAX_AGE_SECONDS
            ),
        )
        .first()
    )
    if existing:
        return existing
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
    send_macos_alert(disaster_type, risk_level, region_name)
    send_sms_alert(disaster_type, risk_level, region_name, sms_recipients)
    send_telegram_alert(disaster_type, risk_level, region_name)
    send_email_alert(disaster_type, risk_level, region_name, settings.EMAIL_TO)
    return alert
