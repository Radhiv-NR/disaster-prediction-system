# Disaster monitoring for AP and Telangana

A small Flask control room for watching current weather, testing risk scenarios,
and sending alerts from a local machine. It covers Andhra Pradesh and Telangana,
with SQLite for an easy local start and MySQL when the app is deployed more
permanently.

## What it does

- Live weather monitoring across multiple regional stations
- Weather-based prediction for flood, cyclone, wildfire, or calm conditions
- Real-time dashboard updates using Server-Sent Events
- 3D regional risk map and telemetry chart
- Alert feed that can be filtered by risk, hazard, and state
- Voice alerts in English, Hindi, and Telugu
- Offline macOS Notification Center alerts
- SIM7600 GSM SMS alert support
- Telegram alerts for a group or a list of users
- What-if simulator for testing different weather conditions
- MySQL support with an automatic SQLite fallback for local development

## Tech stack

- Python
- Flask
- SQLAlchemy
- scikit-learn
- pandas and numpy
- Open-Meteo weather API and OpenStreetMap tiles through Leaflet
- MySQL / SQLite
- Chart.js and Three.js
- pyttsx3
- joblib

## Project structure

```text
disaster-prediction/
├── app.py
├── alert_system.py
├── config.py
├── database.py
├── disaster_data_generator.py
├── model_training.py
├── weather_service.py
├── requirements.txt
├── setup_database.sql
├── data/
│   └── andhra_telangana_disasters.csv
├── logs/
├── models/
├── static/
│   ├── css/
│   └── js/
├── templates/
│   └── index.html
└── README.md
```

## Before you start

- Python 3.12
- MySQL 8.4, if you do not want to use the local SQLite database
- pip

## Setup

1. Create a virtual environment

```bash
python3.12 -m venv venv
source venv/bin/activate
```

2. Install dependencies

```bash
pip install --upgrade pip
pip install -r requirements.txt
```

3. Copy `.env.example` to `.env` and replace the placeholders. Start with the
weather settings below; the other alert channels can stay disabled until you
configure them.

Open-Meteo does not require an API key. Use these settings:

```env
WEATHER_PROVIDER=open_meteo
WEATHER_ENABLED=true
```

The dashboard uses OpenStreetMap tiles through Leaflet, so no browser map key
is needed. Keep `.env` out of version control.

## Start the dashboard

```bash
python app.py
```

Open:

```text
http://127.0.0.1:8000
```

## Production deployment

Use a WSGI server instead of `python app.py` in production:

```bash
gunicorn --bind 0.0.0.0:8000 --workers 2 --threads 4 wsgi:app
```

Set these values in the deployment environment:

```env
FLASK_DEBUG=false
FLASK_HOST=0.0.0.0
CORS_ORIGINS=https://your-dashboard.example.com
SIMULATOR_ENABLED=false
LIVE_ALERTS_ENABLED=true
```

Use MySQL for a multi-worker deployment. Keep `.env` and all provider
credentials outside version control, and put the service behind HTTPS and an
authentication layer before exposing it to the public internet.

## How the pieces fit together

- The app seeds 29 monitoring regions. The simulator produces a reading for one
	region at a time, while the live alert worker checks configured regions on its
	own interval.
- The classifier is trained from generated calibration scenarios. Live
	predictions use the five weather fields supplied by the provider; an
	earthquake cannot be inferred from weather alone.
- The place catalog contains 40,026 populated places. It is searched in pages
	so opening the dashboard does not issue thousands of weather requests at
	once. Try `/api/places?q=place-name&state=Telangana` and then
	`/api/weather?place_id=GEONAMES_ID`.
- SMS delivery needs a connected SIM7600 modem and recipients saved in the
	dashboard. Email and Telegram are separate channels with their own settings.
- Hindi and Telugu voice alerts depend on matching voices being installed on
	the host machine.

### Offline alerts on macOS

macOS Notification Center and the built-in `say` voice engine work without
internet access. Enable them in `.env`:

```env
MACOS_NOTIFICATIONS_ENABLED=true
MACOS_NOTIFICATIONS_MIN_RISK=high
TTS_ENABLED=true
```

The local dashboard, simulator, database, voice alerts, and macOS notifications
work offline. Live weather updates require an internet connection. Sending a
message to people on other devices while completely offline requires a local
Wi-Fi/LAN receiver, radio, or a working cellular modem such as the SIM7600.

### Free Telegram alerts

Telegram is the recommended alert channel when a SIM7600 is unavailable. It
does not require a paid SMS provider or extra Python package.

1. In Telegram, open `@BotFather`, run `/newbot`, and copy the bot token.
2. Add the bot to a Telegram group, or have each recipient open the bot and
	press **Start**.
3. Get the group or user chat ID. A simple method is to send a message in the
	chat, then open:
	`https://api.telegram.org/botYOUR_TOKEN/getUpdates`
4. Set these values in `.env`:

```env
TELEGRAM_ENABLED=true
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_IDS=-1001234567890,123456789
TELEGRAM_MIN_RISK=high
```

Restart the app and test delivery:

```bash
curl -X POST http://127.0.0.1:8000/api/telegram/test \
  -H 'Content-Type: application/json' \
  -d '{"message":"Telegram alert test"}'
```

Use a Telegram group chat ID to notify many people with one entry. Keep the
bot token private and never commit it to source control.
