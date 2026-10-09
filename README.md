# PPE Safety Platform (v2)

Real-time PPE compliance monitoring for Solar Industries plants. A YOLO model watches the CCTV network for missing helmets, gloves, goggles, masks, shoes and suits. Violations go to supervisors by email and to a web portal. The portal is also where people improve the model: they review false alarms, annotate missed or rare cases and retrain, all without code changes.

## What runs where

| Component | Path | Runs as | Does |
|---|---|---|---|
| API | `backend/` (FastAPI, SQLAlchemy, Alembic) | `ppe-api` | Auth (password + emailed OTP), permissions, dashboards, review, annotation, configuration, datasets, training jobs, model registry |
| Web portal | `frontend/` (Next.js 16, Tailwind, Smart Factory design system) | `ppe-web` | Every screen; proxies `/api` to the API |
| Inference | `inference.py` | `ppe-inference` | One thread per enabled camera; cameras, PPE rules, class thresholds and the active model come from the database and reload without a restart; saves the annotated alert image, the clean frame and every model box |
| Trainer | `trainer.py` | `ppe-trainer` | Runs queued training jobs on the GPU, pausing inference for the duration; registers the result as a new (inactive) model |
| Alert mailer | `cooldown.py` | `ppe-cooldown` | Emails each violation to the production house's recipients (6 h debounce per area); skips false positives |
| Health digest | `camera_status_mail.py` | `ppe-health-mail` | Daily 10:00 list of offline cameras |

Shared state is PostgreSQL plus MinIO. The workers find out about changes by polling `runtime_state` (config version, pause flag, active model). They report back through `worker_heartbeats`.

## Permissions

`admin` holds everything. Admins grant the rest per user under *Administration → Users & permissions*:

| Permission | Allows |
|---|---|
| View dashboard | Dashboard, alert emails, Excel export (everyone) |
| Review detections | Mark detections real or false positive; correct boxes into training data |
| Annotate images | Upload images, capture camera frames, draw boxes, submit for QA |
| Approve annotations | Accept labelled images into the training pool (YOLO `images/` + `labels/` in MinIO) |
| Manage cameras | Plants, production houses, areas, cameras, stream addresses |
| Manage PPE rules | Required PPE per area, PPE types, classes, confidence thresholds |
| Manage alert recipients | Who gets violation emails and the health digest |
| Retrain models / Manage users | Administrators only |

## Improving the model, end to end

1. **Review**: a reviewer opens a detection, fixes the boxes on the clean frame (for example *No Helmet* → *Helmet*) and marks it a false positive or a real violation. False positives drop out of the dashboards.
2. **Annotate**: for missed detections or rare classes, upload photos or grab frames from a camera and box every PPE item. The class-balance panel shows which classes are short of examples.
3. **QA**: an approver accepts the labels. Each approved image is written to `training-pool/` in YOLO format.
4. **Dataset**: an admin freezes the pool into a dataset version. Train/val splits are stratified by area and never change for an image.
5. **Train**: an admin queues a run, and `trainer.py` pauses inference, fine-tunes, evaluates the new and the active model on the same validation split, then resumes inference.
6. **Promote**: an admin compares the metrics per class and activates the better model. Inference loads it within about 30 s, and activating the previous model rolls back.

## Local development

```bash
# API: Python 3.10+
cd backend
python -m venv .venv && .venv/Scripts/pip install -r requirements-dev.txt     # Linux/macOS: .venv/bin/pip
cp .env.example .env    # DB_*, SECRET_KEY; COOKIE_SECURE=false and DEV_PRINT_EMAILS=true for local work
alembic upgrade head
python -m app.cli import-cameras ../legacy/config/camera_list_v4_newplants.json
python -m app.cli import-recipients seed/recipients.json
python -m app.cli create-admin first.last@solargroup.com
uvicorn app.main:app --reload --port 8000                                       # docs: http://localhost:8000/api/docs
pytest

# Web: Node 20.9+
cd frontend
npm install
npm run dev             # http://localhost:3000; /api is proxied to API_ORIGIN (default http://127.0.0.1:8000)

# Worker logic tests (no GPU needed)
backend/.venv/Scripts/python -m pytest worker_tests
```

With no S3 credentials, the API and workers store objects under `var/storage/` instead of MinIO. With `DEV_PRINT_EMAILS=true`, sign-in codes are printed to the API log.

## Documentation

- `docs/DEPLOYMENT.md`: cutover runbook for the GPU server, verification and rollback
- `docs/MIGRATION_PLAN.md`: design decisions and what changed from v1
- `SKILL.md`: Smart Factory UI design system
- `legacy/`: the v1 Flask portal, camera JSON files and old scripts, kept for rollback
- `PPE_Detection_Knowledge_Transfer_Document.md`: v1 knowledge-transfer document (historical)
