# Deploying PPE platform v2 (cutover runbook)

Target: the Ubuntu 22.04 GPU server that already runs `inference.py`, `cooldown.py`, `camera_status_mail.py` and the Flask portal, under `/home/administrator/PPEsDetection` as user `administrator`. Adjust paths in `deploy/` if yours differ.

All database changes are additive (new tables, new nullable columns on `ppes`). The legacy Flask portal keeps working against the migrated database, which is what makes rollback cheap.

## 0. Before you start

- Take a database backup: `pg_dump -Fc ppes > ppes-before-v2.dump`.
- **Check the legacy schema.** `backend/alembic/versions/0001_legacy_baseline.py` describes `users`, `password_history`, `otps`, `activity_logs`, `ppes`, `camera_health` and `ppes_emails_records` as the old code uses them. Compare against `\d users`, `\d activity_logs` and the others in `psql`. Column names matter; small type differences (varchar vs text) don't.
- Install **Node.js 20.9 or newer** (Ubuntu's default `nodejs` is too old). NodeSource or nvm both work.
- Pick a maintenance window of about 30 minutes. Live detection stops while the workers are swapped.

## 1. Code and Python environments

```bash
cd /home/administrator/PPEsDetection
git fetch && git checkout <release branch or tag>

# API
python3 -m venv backend/.venv
backend/.venv/bin/pip install -r backend/requirements.txt
# Optional: "Suggest boxes" in the annotation screen (runs on CPU in the API)
backend/.venv/bin/pip install -r backend/requirements-ml.txt

# Workers (the existing venv that ran inference.py)
venv/bin/pip install -r requirements-workers.txt
```

`.env` at the repo root is shared. Compare it with `.env.example`. These variables are new or changed:

| Variable | Notes |
|---|---|
| `DB_PASS` | Raw password. The workers no longer fall back to a hard-coded password. |
| `SECRET_KEY` | Signs portal sessions. Keep it long and random. |
| `APP_BASE_URL` | Public URL of the new portal, used in password-reset emails. |
| `INTERNAL_S3_ENDPOINT_URL`, `S3_VERIFY_TLS` | How the API and workers reach MinIO on the server. |
| `PUBLIC_IMAGE_BASE` | Base of `ppes.image_url` (defaults to the current host). |

## 2. Database

```bash
cd backend
# The production DB already has the legacy tables: record that instead of creating them
.venv/bin/alembic stamp 0001_legacy
.venv/bin/alembic upgrade head        # 0002 permissions/OTPs, 0003 platform v2 (+ seeds)
```

`0003` seeds the six PPE items, the 12-class registry with the thresholds that were hard-coded in the old `inference.py`, and `model/best12classes.pt` as the active model.

## 3. Load the configuration that used to live in files

```bash
# Cameras. The old systemd unit ran only camera_list_v4_newplants.json (72 cameras),
# while the script's default was camera_list_v4.json (364). Import what should be live;
# add --disabled to import a file's cameras switched off.
.venv/bin/python -m app.cli import-cameras ../legacy/config/camera_list_v4_newplants.json
.venv/bin/python -m app.cli import-cameras ../legacy/config/camera_list_v4.json --disabled   # optional

# Alert recipients (extracted from cooldown.py / camera_status_mail.py / app.py)
.venv/bin/python -m app.cli import-recipients seed/recipients.json
```

The recipient import prints mismatches. On the current data:

- **Houses with cameras but no recipients** (their alerts have been going nowhere): DF01, GB-01, HD-1, HD-2, HD-3, HD-5, PB-1–PB-6, PP-25, PP-26, RCGB-2–RCGB-6.
- **Recipient lists for houses with no cameras** (probably name mismatches): DF-01, GB, HRCPCH-02, PD-10, PP-02, PP-07, PP-08.

Fix these in the portal under *Configuration → Alert recipients* after go-live.

Existing users keep their passwords. Make sure at least one admin exists (`python -m app.cli create-admin first.last@solargroup.com` if not), then grant permissions from *Administration → Users & permissions*.

## 4. Build and install services

```bash
cd frontend
npm ci
API_ORIGIN=http://127.0.0.1:8001 npm run build

sudo cp ../deploy/systemd/*.service /etc/systemd/system/
sudo systemctl daemon-reload

# Swap the workers (stops live detection briefly)
sudo systemctl stop ppe-inference ppe-cooldown ppe-health-mail
sudo systemctl enable --now ppe-api ppe-web ppe-inference ppe-trainer ppe-cooldown ppe-health-mail
```

The new `ppe-inference.service` runs `python inference.py` with no `--cameras` argument; cameras come from the database.

Then the reverse proxy. Copy `deploy/nginx/ppe.conf` into `/etc/nginx/sites-available/`, set the certificate paths, enable it and run `sudo nginx -t && sudo systemctl reload nginx`. During a trial period the old Flask portal (`ppe-dashboard.service`, port 8000) can keep running on an internal address. Its code is in `legacy/flask_portal/`; start it from there.

## 5. Verify

1. Sign in at `https://ppes-siil.solargroup.com` (password plus emailed code).
2. *Training & models → Overview*: inference shows **Running** with N of N cameras and the baseline model, and the trainer shows **Idle**.
3. Within a few minutes the dashboard shows new events. *Review detections* with "Only events usable for training" lists events with a clean frame.
4. Change a threshold in *PPE & classes*. `journalctl -u ppe-inference` logs `Config vN applied` within about 30 s.
5. Force a test alert (`TEST_MODE=True` for `ppe-cooldown`) and check it goes to the house's recipients from the database.

## 6. Retraining on the shared GPU

Training and live detection share the A40. When a run starts, `trainer.py` pauses inference: streams are released and the model is unloaded. Inference resumes automatically when no runs are left in the queue. Every page shows a banner while detection is paused. Prefer starting runs off-shift. A promoted model is loaded by inference on its next poll, and activating the previous model rolls back.

## 7. Rollback

1. `sudo systemctl stop ppe-inference ppe-trainer ppe-cooldown ppe-health-mail ppe-api ppe-web`
2. Restore the previous scripts with `git checkout <previous tag> -- inference.py cooldown.py camera_status_mail.py`. Point the old inference at the moved camera list (`python inference.py --cameras legacy/config/camera_list_v4_newplants.json`), and run the Flask portal from `legacy/flask_portal/` (`python app.py`; it finds the root `.env`).
3. Start the previous units. The extra tables and columns don't affect the old code, so no database restore is needed.
