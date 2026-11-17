import email.message

import alert_system


def test_send_email_alert_uses_smtp(monkeypatch):
    calls = {}

    class DummySMTP:
        def __init__(self, host, port, timeout=None):
            calls["connect"] = (host, port)

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def starttls(self):
            calls["starttls"] = True

        def login(self, username, password):
            calls["login"] = (username, password)

        def send_message(self, msg):
            calls["message"] = msg

    monkeypatch.setattr(alert_system.settings, "EMAIL_ENABLED", True)
    monkeypatch.setattr(alert_system.settings, "EMAIL_MIN_RISK", "high")
    monkeypatch.setattr(alert_system.settings, "EMAIL_FROM", "alerts@example.com")
    monkeypatch.setattr(alert_system.settings, "EMAIL_TO", ["ops@example.com"])
    monkeypatch.setattr(alert_system.settings, "SMTP_HOST", "smtp.example.com")
    monkeypatch.setattr(alert_system.settings, "SMTP_PORT", 587)
    monkeypatch.setattr(alert_system.settings, "SMTP_USERNAME", "demo")
    monkeypatch.setattr(alert_system.settings, "SMTP_PASSWORD", "secret")
    monkeypatch.setattr(alert_system.settings, "SMTP_USE_TLS", True)
    monkeypatch.setattr(alert_system.settings, "SMTP_TIMEOUT_SECONDS", 10)
    monkeypatch.setattr(alert_system, "RISK_RANK", {"none": 0, "low": 1, "medium": 2, "high": 3, "critical": 4})

    import smtplib
    monkeypatch.setattr(smtplib, "SMTP", DummySMTP)

    result = alert_system.send_email_alert("flood", "high", "Vijayawada")

    assert result["sent"] == 1
    assert calls["connect"] == ("smtp.example.com", 587)
    assert calls["login"] == ("demo", "secret")
    assert calls["message"].get("Subject") == "Disaster Alert: flood risk is HIGH in Vijayawada"
