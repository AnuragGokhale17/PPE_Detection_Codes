# PPE platform v2: design and what changed from v1

Status: all phases implemented on branch `feature/fastapi-nextjs-migration`. Production cutover follows `docs/DEPLOYMENT.md`.

## 1. v1 in brief

```
camera_list_v4*.json ──► inference.py ──► MinIO (annotated JPEG) + PostgreSQL `ppes`, `camera_health`
                                                 ├──► app.py (Flask portal)
                                                 ├──► cooldown.py (alert emails, recipients hard-coded)
                                                 └──► camera_status_mail.py (daily digest, recipients hard-coded)
```

Cameras, required PPE, class thresholds and email recipients were all in code or JSON, so every change needed a developer and a restart. The stored evidence images had boxes and the HUD drawn on them, which made them useless as training data.

## 2. v2 architecture

```
browser ── nginx ──► Next.js (frontend/) ── /api ──► FastAPI (backend/) ──► PostgreSQL + MinIO
                                                                   ▲
                       inference.py · trainer.py · cooldown.py · camera_status_mail.py
                       (poll runtime_state; report worker_heartbeats)
```

Decisions:

- **The database is the source of truth for configuration.** The `cameras`, `camera_ppe`, `ppe_items`, `model_classes` and `alert_recipients` tables replace the JSON files and hard-coded dicts. Each portal edit bumps `runtime_state.config_version`. Inference re-reads it every 30 s and starts, stops or restarts only the cameras that changed.
- **The database holds the labels, and YOLO files are written alongside.** `samples` and `sample_labels` hold the boxes, and every approval writes `training-pool/images|labels/<id>`. A dataset version freezes the pool to `datasets/<name>/images|labels/{train,val}` plus `data.yaml`. An image keeps its split for life, so validation scores stay honest across versions.
- **Training shares the inference GPU.** `trainer.py` pauses inference (streams released, model unloaded, cameras not marked offline), trains, evaluates the new and active models on the same split, and resumes inference when the queue is empty. A pause set by an admin is never lifted by the trainer.
- **Models live in a registry.** `model_versions` records every model. Activation sets `runtime_state.active_model_id`, inference hot-swaps the weights and keeps the old ones if loading fails, and rollback means activating the previous model.
- **The class registry is stable.** Class ids are YOLO indices, appended and never reused. A new PPE type gets "<Name>" and "No <Name>" classes, which are annotated and trained before the model can detect them.
- **Auth follows the old rules, made stricter.** These are unchanged: 14-character complexity, 30-day expiry, last-5 history, 3 failures → 30 min lock, emailed OTP, 10-minute idle timeout. Additions: hashed OTPs with an attempt limit, single-use reset links, sessions that end when the password changes, and sessions in httpOnly cookies.
- **Coexistence.** Database changes are additive only, so the v1 scripts and portal still run against a migrated database.

## 3. Feature map

| Request | Where |
|---|---|
| FastAPI backend | `backend/app/routers/*`, 44 tests in `backend/tests` |
| Next.js frontend | `frontend/src/app/*` (20 routes) |
| Mark false positives, stored in YOLO format | *Review detections* → `POST /api/events/{id}/review` → sample → `training-pool/` |
| Annotate missed or under-represented classes | *Annotate*: upload, camera snapshot, model suggestions, class balance, QA |
| Retrain (admin only) | *Training & models*: datasets, runs, comparison, promote/rollback; `trainer.py` |
| Add cameras and areas, change PPE from the UI | *Cameras & areas*, *PPE & classes*, *Alert recipients* |
| Admin grants these rights per user | *Users & permissions* (permission catalogue in `backend/app/core/permissions.py`) |

## 4. Problems found in v1 (fixed in v2)

- **About 186 cameras were never monitored.** `inference.py` submitted one never-ending task per camera to a `ThreadPoolExecutor(max_workers=250)`, so with 364 cameras the rest never started. v2 runs one thread per camera.
- **Alerts went nowhere for 19 production houses.** The recipient dict didn't cover DF01, GB-01, HD-1/2/3/5, PB-1–6, PP-25, PP-26 or RCGB-2–6. Seven recipient lists were keyed by names no camera uses ("DF-01" vs "DF01", "GB" vs "GB-01", …). The import reports both lists; fix them under *Alert recipients*.
- **Duplicate PPE entries** in `camera_list_v4.json` (PP-09 / CARTRIADGE_FILLING_AREA lists goggles twice). The importer now de-duplicates.
- **SQL built from request input.** The Flask dashboard f-stringed filters into SQL. All queries are parameterised now.
- **"Clear violation" was available to any signed-in user and left no record.** Reviews are now permission-gated and audited.
- **`/debug-ip` was unauthenticated and the Flask app ran with `debug=True`.** Both are gone with the Flask portal.
- **`inference.py` fell back to a hard-coded database password.** That fallback is removed.

## 5. Verification done

- **Backend tests:** 44 pytest cases (auth, permissions, config, dashboards, review → YOLO files, annotation QA, dataset splits, training queue, model activation), with migrations applied to SQLite.
- **Worker tests:** 26 pytest cases for the logic (class mapping, camera diffing, detection payloads, `data.yaml`, progress and metrics shapes).
- **Real-data import:** both camera JSON files (366 cameras) and the extracted recipient lists (380 addresses).
- **Browser walkthrough:** headless Edge against the production build covered every screen, the review and annotation flows (YOLO files checked in storage), dataset build, queueing a run, role-restricted navigation, and no horizontal scrolling at 390 px.
- **Not yet exercised:** a real GPU, RTSP cameras, SMTP and PostgreSQL-specific SQL in the workers (`FOR UPDATE SKIP LOCKED`, JSONB). Check these during the cutover verification in `docs/DEPLOYMENT.md`.
