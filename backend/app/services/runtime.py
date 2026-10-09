"""Shared runtime state the GPU workers poll (config version, pause flag, active model)."""
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.security import as_utc, utcnow
from app.db.models import RuntimeState, WorkerHeartbeat

# A worker that hasn't checked in for this long is shown as offline
HEARTBEAT_STALE_AFTER = timedelta(minutes=2)


def get_state(db: Session) -> RuntimeState:
    state = db.get(RuntimeState, 1)
    if state is None:
        state = RuntimeState(id=1, config_version=1, inference_paused=False)
        db.add(state)
        db.flush()
    return state


def bump_config_version(db: Session, by: str) -> int:
    """Call inside the transaction that changes cameras, PPE rules or classes.
    inference.py reloads its configuration when it sees the new number."""
    state = get_state(db)
    state.config_version += 1
    state.updated_at = utcnow()
    state.updated_by = by
    return state.config_version


def set_inference_paused(db: Session, paused: bool, reason: str | None, by: str) -> RuntimeState:
    state = get_state(db)
    state.inference_paused = paused
    state.pause_reason = reason if paused else None
    state.updated_at = utcnow()
    state.updated_by = by
    return state


def worker_status(db: Session) -> dict[str, dict]:
    now = utcnow()
    result = {}
    for hb in db.scalars(select(WorkerHeartbeat)).all():
        last_seen = as_utc(hb.last_seen)
        result[hb.name] = {
            "last_seen": last_seen,
            "online": bool(last_seen and now - last_seen < HEARTBEAT_STALE_AFTER),
            "info": hb.info or {},
        }
    return result
