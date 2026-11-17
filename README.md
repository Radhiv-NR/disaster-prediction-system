# Real-Time Disaster Prediction & Alert System

Flask + ML (RandomForest) + MySQL 8.4 + glassmorphic 3D dashboard (Three.js) focused on **Andhra Pradesh & Telangana**.

Live sensor simulation → ML prediction → SSE push → multilingual voice (English / Hindi / Telugu) → optional Twilio SMS.

---

## Project layout

```
disaster-prediction/
├── app.py                      # Flask entrypoint (routes, simulator, SSE)
├── config.py
├── database.py                 # SQLAlchemy models + AP/TS region seed
├── alert_system.py             # SSE · pyttsx3 (en/hi/te) · Twilio SMS
├── disaster_data_generator.py
├── model_training.py
├── requirements.txt
├── setup_database.sql          # Run in MySQL Workbench
├── .env.example
├── data/
│   └── andhra_telangana_disasters.csv   # Two-state labelled sections
├── logs/
├── models/                     # disaster_model.joblib written at first run
├── static/css/style.css
├── static/js/script.js
└── templates/index.html
```

---

## 1. Prerequisites (macOS)

### 1.1 Python 3.14

```bash
brew install python@3.14
echo 'export PATH="/opt/homebrew/opt/python@3.14/bin:$PATH"' >> ~/.zshrc
source ~/.zshrc
python3.14 --version
```

### 1.2 MySQL 8.4

```bash
brew install mysql@8.4
echo 'export PATH="/opt/homebrew/opt/mysql@8.4/bin:$PATH"' >> ~/.zshrc
source ~/.zshrc
brew services start mysql@8.4
mysql_secure_installation   # set root password (one-time CLI step)
```

### 1.3 MySQL Workbench

```bash
brew install --cask mysqlworkbench
```

Open Workbench → create a connection to `127.0.0.1:3306` as `root` → Test Connection.

---

## 2. Get the project

```bash
cd ~/Documents/disaster-prediction   # or wherever you unzipped it
ls   # should show app.py, setup_database.sql, …
```

---

## 3. Database setup (MySQL Workbench)

1. **File → Open SQL Script…** → select `setup_database.sql`
2. Change the password on the `CREATE USER` line
3. Click the **yellow lightning bolt** (Execute)
4. Confirm in the Output panel (green checks) and Result Grid:
   - `disaster_prediction_db` exists
   - `disaster_user` exists
5. Right-click **SCHEMAS → Refresh All** if the schema doesn’t appear yet

Tables (`regions`, `sensor_readings`, `prediction_logs`, `alerts`) are created automatically the first time you run `python app.py`.

---

## 4. Python environment

```bash
cd ~/Documents/disaster-prediction
python3.14 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

Pinned stack:

```
Flask==2.3.0
Flask-CORS==4.0.0
pandas==2.2.3
numpy==1.26.4
scikit-learn==1.4.2
mysql-connector-python==8.2.0
requests==2.31.0
python-dotenv==1.0.0
pyttsx3==2.90
joblib==1.4.2
Werkzeug==2.3.0
SQLAlchemy==2.0.30
```

---

## 5. Configure `.env`

```bash
cp .env.example .env
```

Set `DB_PASSWORD` to the **same** password you used in `setup_database.sql` for `disaster_user`.

Optional:

| Variable | Meaning |
|---|---|
| `TTS_ENABLED` | Voice alerts on/off (default `true`) |
| `TTS_MIN_RISK` | `high` or `critical` |
| `TTS_LANGUAGE` | `en` / `hi` / `te` |
| `SMS_ENABLED` | Twilio SMS (default `false`) |
| `SIMULATOR_INTERVAL_SECONDS` | Demo feed speed |

---

## 6. Run

```bash
source venv/bin/activate
python app.py
```

Open **http://127.0.0.1:8000**

First launch trains the model (~10s) and seeds 14 AP/Telangana stations.

---

## 7. Voice alerts (English · Hindi · Telugu)

Dashboard top bar: language dropdown + Voice On/Off.

- English ships with macOS
- Hindi: system voice **Lekha** (usually preinstalled)
- Telugu: add a Telugu voice in **System Settings → Accessibility → Spoken Content → System Voice** if you want native pronunciation; otherwise it falls back gracefully

Threshold controlled by `TTS_MIN_RISK`.

---

## 8. SMS alerts (Twilio)

1. Create a free account at [twilio.com](https://www.twilio.com)
2. Copy Account SID, Auth Token, and a From number
3. Put them in `.env` along with `SMS_TO_NUMBERS=+91XXXXXXXXXX`
4. Set `SMS_ENABLED=true`
5. **Trial accounts** can only text verified numbers (Twilio Console → Verified Caller IDs)

Dashboard shows an **SMS** pill; `POST /api/sms/test` sends a trial message.

---

## 9. Regional training data

`data/andhra_telangana_disasters.csv` is split into:

- **SECTION 1: ANDHRA PRADESH** — flood / cyclone / earthquake / wildfire / calm
- **SECTION 2: TELANGANA** — same disaster types

Rows are blended into synthetic training data so the model is grounded in local geography. They are plausible scenarios, not claimed historical instrument readings.

---

## 10. Common issues

| Symptom | Fix |
|---|---|
| Workbench can’t connect | `brew services start mysql@8.4`; check port 3306 |
| Schema missing in sidebar | Right-click SCHEMAS → Refresh All |
| Access denied for `disaster_user` | Password in `.env` must match `setup_database.sql` |
| App falls back to SQLite | MySQL not reachable — fine for UI testing; fix credentials for production |
| No voice on Linux CI | Expected — pyttsx3 needs a speech driver; macOS uses built-in |
| SMS not sending | Credentials empty or trial number not verified |
| `SOURCE setup_database.sql` path error in CLI | Prefer Workbench; or `mysql -u root -p < /full/path/setup_database.sql` |

---

## API quick reference

| Method | Path | Purpose |
|---|---|---|
| GET | `/api/health` | Liveness |
| GET | `/api/regions` | Seeded stations |
| POST | `/api/sensors/ingest` | Push a reading |
| POST | `/api/predict` | What-if only (no DB write) |
| GET | `/api/alerts` | Recent alerts |
| GET | `/api/telemetry` | Recent sensor series |
| GET | `/stream/live` | SSE (sensor + alert events) |
| GET/POST | `/api/tts/*` | Status, toggle, language, speak |
| GET/POST | `/api/sms/*` | Status, toggle, test |

---

## Stop

`Ctrl+C` in the app terminal. Optionally `brew services stop mysql@8.4`.
