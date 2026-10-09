# Legacy (v1) code, kept for rollback

Nothing here runs in the v2 deployment. Kept so the old setup can be restored quickly (see `docs/DEPLOYMENT.md`, Rollback). Delete once v2 has been stable for a while.

| Path | Was | Replaced by |
|---|---|---|
| `flask_portal/` | Flask dashboard, OTP login, admin panel (`app.py`, `auth.py`, `templates/`, `static/`, `create_admin.py`, `layouts.py`) | `backend/` (FastAPI) + `frontend/` (Next.js); `python -m app.cli create-admin` |
| `config/camera_list_*.json` | Camera, area and required-PPE configuration | `cameras`, `camera_ppe`, `ppe_items` tables, edited under *Configuration → Cameras & areas*; `python -m app.cli import-cameras` / `export-cameras` |
| `scripts/collect_retraining_data.py` | Separate collector writing model-labelled frames to S3 | Clean frames saved with every event, review + annotation screens, `trainer.py` |
| `scripts/camera_monitoring.py` | Second RTSP prober (already deprecated) | `inference.py` maintains `camera_health` |
| `scripts/ppe_detection_code*.py`, `ppes_detection_code_sel.py`, `ppes_test.py` | Earlier inference versions | `inference.py` |
| `scripts/email_utils.py` | Unused email helper | `cooldown.py`, `backend/app/services/mailer.py` |

`flask_portal/app.py` still runs against the migrated database (`cd legacy/flask_portal && python app.py`); v2 only adds tables and nullable columns.
