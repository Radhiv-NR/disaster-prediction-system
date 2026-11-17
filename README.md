# Andhra Pradesh & Telangana Disaster Monitoring

A local dashboard for exploring weather conditions and estimated disaster risk
across Andhra Pradesh and Telangana. It brings regional weather, a small
machine-learning experiment, a what-if simulator, and optional alert channels
into one Flask app.

> **Please treat this as a prototype, not an official warning service.** Its
> predictions are estimates from a rule-assisted model trained on generated
> scenarios. They are not validated emergency guidance and must not replace
> official weather or disaster-management advisories.

## What you can do

- View monitoring regions and search a catalog of places in both states.
- See current weather when the configured provider and internet connection are
  available.
- Review estimated flood, cyclone, wildfire, and no-hazard conditions, along
  with recent alerts and sensor telemetry.
- Watch the dashboard update through a live server-sent event stream.
- Adjust weather inputs in the what-if simulator without sending a sensor
  reading.
- Configure optional voice, macOS notification, SIM7600 SMS, Telegram, and
  email alerts.

The app starts with a simulator enabled, so it can produce sample readings for
the dashboard. When live weather is enabled but unavailable, simulator readings
are skipped rather than presented as current weather. Disable live weather to
use simulated readings without an internet connection.

## How predictions work

The model uses five weather inputs: temperature, relative humidity, rainfall,
wind speed, and surface pressure. The training code builds generated
calibration scenarios and fits a scikit-learn random-forest pipeline. A small
set of weather thresholds also identifies severe conditions before the model
is used.

This is **not** a model trained or validated on a comprehensive, independently
verified history of disasters. Weather alone cannot detect earthquakes, and
the simulator's seismic, river, and soil-moisture values do not make those
hazards predictable in the current model. Treat displayed risk as experimental.

## Project layout

| Path | Purpose |
| --- | --- |
| `app.py` | Flask pages, API routes, simulator, and live alert checks |
| `alert_system.py` | Live event broadcasting and optional notification channels |
| `config.py` | Reads settings from `.env` |
| `database.py` | SQLAlchemy models, default monitoring regions, and database setup |
| `weather_service.py` | Open-Meteo or Google Weather lookups with a short cache |
| `disaster_data_generator.py` | Generated training scenarios and simulator readings |
| `model_training.py` | Train, load, and run the weather-risk model |
| `wsgi.py` | WSGI entry point for Gunicorn |
| `templates/`, `static/` | Dashboard HTML, styles, and browser-side code |
| `data/ap_telangana_places.csv` | Place names and coordinates used by search and maps |
| `data/andhra_telangana_disasters.csv` | Regional disaster dataset included with the project |
| `data/disaster_local.db` | Local SQLite database, used when MySQL is unavailable |
| `setup_database.sql` | Optional MySQL database and user setup |
| `tests/` | Focused prediction and email-alert tests |

## Requirements

- Python 3.12
- `pip`
- Internet access for live weather and Telegram/email delivery
- Optional: MySQL, a SIM7600 modem, and provider credentials for the related
  integrations

The app tries MySQL using the `DB_*` settings. If it cannot connect, it uses
`data/disaster_local.db` instead. For local development, MySQL is optional.

## Run locally

From the project directory:

```bash
python3.12 -m venv venv
source venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
cp .env.example .env
python app.py
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000). Leave the terminal running
while you use the dashboard; press **Ctrl+C** to stop the server.

On macOS, if `python` is not on your shell's `PATH`, you can run the app with
the virtual-environment interpreter directly:

```bash
./venv/bin/python app.py
```

The server creates database tables and default monitoring regions at startup.
If the model file is missing, it trains and saves one under `models/`.

### Weather and offline development

The default provider is Open-Meteo, which does not need an API key. Live
lookups do need an internet connection. Set these in `.env`:

```env
WEATHER_PROVIDER=open_meteo
WEATHER_ENABLED=true
```

To run with generated readings only, set `WEATHER_ENABLED=false`. The simulator
is controlled separately by `SIMULATOR_ENABLED`; live alert checks are
controlled by `LIVE_ALERTS_ENABLED`. Restart the app after changing `.env`.

Google Weather is also supported by the code. To use it, set
`WEATHER_PROVIDER=google` and configure `GOOGLE_WEATHER_API_KEY`. Google Maps
tiles are optional and use `GOOGLE_MAPS_API_KEY`.

## Optional alert channels

All alert integrations can remain disabled while you explore the local
dashboard. Configure only the channels you intend to use, keep credentials in
`.env`, and never commit that file.

| Channel | Configuration | Notes |
| --- | --- | --- |
| Voice | `TTS_ENABLED`, `TTS_LANGUAGE`, `TTS_MIN_RISK` | Uses the host's speech engine. Hindi and Telugu voices depend on the operating system. |
| macOS notifications | `MACOS_NOTIFICATIONS_ENABLED`, `MACOS_NOTIFICATIONS_MIN_RISK` | Local Notification Center integration; available on macOS. |
| SIM7600 SMS | `SMS_ENABLED`, `GSM_PORT`, `GSM_BAUDRATE`, `GSM_TO_NUMBERS`, `SMS_MIN_RISK` | Requires a connected, working modem. Saved dashboard recipients can be used for broadcasts. |
| Telegram | `TELEGRAM_ENABLED`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_IDS`, `TELEGRAM_MIN_RISK` | Create a bot with BotFather and start a chat with it (or add it to a group). Keep its token private. |
| Email | `EMAIL_ENABLED`, `EMAIL_FROM`, `EMAIL_TO`, `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `SMTP_USE_TLS`, `EMAIL_MIN_RISK` | Requires an SMTP server and valid sender/recipient details. |

Each channel has a status and test endpoint in the API. For example, after
configuring Telegram and restarting the app:

```bash
curl -X POST http://127.0.0.1:8000/api/telegram/test \
  -H 'Content-Type: application/json' \
  -d '{"message":"Telegram alert test"}'
```

Testing an integration sends a real notification or message when that channel
is configured. Use your own test recipient.

## API overview

The Flask app serves the dashboard at `/` and provides JSON endpoints for:

- Health, regions, place search, map data, and current weather:
  `/api/health`, `/api/regions`, `/api/places`, `/api/place-map`, `/api/weather`
- Place forecasts and predictions:
  `/api/place-predictions`, `/api/predict`
- Sensor ingestion, alerts, and recent telemetry:
  `/api/sensors/ingest`, `/api/alerts`, `/api/telemetry`
- A live browser event stream: `/stream/live`
- Status, toggles, and tests for voice, macOS notifications, SMS, Telegram, and
  email under `/api/tts`, `/api/macos-notification`, `/api/sms`,
  `/api/telegram`, and `/api/email`

For example:

```bash
curl http://127.0.0.1:8000/api/health
curl 'http://127.0.0.1:8000/api/places?q=Vijayawada&state=Andhra%20Pradesh'
```

Place and forecast endpoints paginate results; see their `limit` and `offset`
query parameters.

## Tests

Run the test suite from the project directory:

```bash
python -m pytest -q
```

## Deployment

For a single-process production example, the project includes Gunicorn:

```bash
gunicorn --bind 0.0.0.0:8000 --workers 2 --threads 4 wsgi:app
```

Before making the dashboard reachable beyond your machine:

- Set `FLASK_DEBUG=false` and configure `FLASK_HOST` and `CORS_ORIGINS`.
- Use MySQL for a multi-worker deployment; SQLite is intended as a simple local
  fallback.
- Put the service behind HTTPS and add authentication and access controls.
- Keep secrets out of source control and use trusted sources for emergency
  decisions.
