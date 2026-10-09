"""Datasets, training runs, the model registry and inference pause/resume (admins only for now)."""
import re

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.deps import CurrentUser, require
from app.core.permissions import Permission
from app.core.security import utcnow
from app.db.models import DatasetVersion, ModelClass, ModelVersion, Sample, TrainingRun, User
from app.db.session import get_db
from app.services import datasets as dataset_svc
from app.services.audit import log_activity
from app.services.runtime import get_state, set_inference_paused, worker_status

router = APIRouter(tags=["training"])
admin = require(Permission.TRAINING_MANAGE)
viewer = require(Permission.DASHBOARD_VIEW)

NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


def _email(db: Session, user_id: int | None) -> str | None:
    return db.scalar(select(User.email).where(User.id == user_id)) if user_id else None


# --- System status ------------------------------------------------------------------


@router.get("/system/status")
def system_status(db: Session = Depends(get_db), _: CurrentUser = Depends(viewer)):
    state = get_state(db)
    active = db.get(ModelVersion, state.active_model_id) if state.active_model_id else None
    running = db.scalar(select(TrainingRun).where(TrainingRun.status == "running").limit(1))
    queued = db.scalar(select(func.count()).select_from(TrainingRun).where(TrainingRun.status == "queued"))
    return {
        "config_version": state.config_version,
        "inference_paused": state.inference_paused,
        "pause_reason": state.pause_reason,
        "paused_by": state.updated_by if state.inference_paused else None,
        "active_model": {"id": active.id, "name": active.name} if active else None,
        "workers": worker_status(db),
        "training": {"running_run_id": running.id if running else None, "queued": queued or 0},
    }


class PauseIn(BaseModel):
    reason: str = Field("Paused by an administrator", max_length=300)


@router.post("/system/inference/pause")
def pause_inference(body: PauseIn, request: Request, db: Session = Depends(get_db), current: CurrentUser = Depends(admin)):
    reason = body.reason.strip() or "Paused by an administrator"
    # trainer.py owns pauses whose reason starts with this; never let a manual pause look like one
    if reason.lower().startswith("retraining run #"):
        reason = f"Manual: {reason}"
    set_inference_paused(db, True, reason, current.email)
    db.commit()
    log_activity(db, request, "Pause Inference", current.id, current.email, reason)
    return {"inference_paused": True}


@router.post("/system/inference/resume")
def resume_inference(request: Request, db: Session = Depends(get_db), current: CurrentUser = Depends(admin)):
    if db.scalar(select(TrainingRun.id).where(TrainingRun.status == "running")):
        raise HTTPException(409, detail="A training run is using the GPU. Cancel it or wait for it to finish.")
    set_inference_paused(db, False, None, current.email)
    db.commit()
    log_activity(db, request, "Resume Inference", current.id, current.email, "Inference resumed")
    return {"inference_paused": False}


# --- Datasets -----------------------------------------------------------------------


def _dataset_out(ds: DatasetVersion, emails: dict) -> dict:
    return {
        "id": ds.id,
        "name": ds.name,
        "status": ds.status,
        "val_ratio": ds.val_ratio,
        "sample_count": ds.sample_count,
        "train_count": ds.train_count,
        "val_count": ds.val_count,
        "class_names": ds.class_names,
        "class_counts": ds.class_counts,
        "notes": ds.notes,
        "error": ds.error,
        "s3_prefix": ds.s3_prefix,
        "created_by": emails.get(ds.created_by),
        "created_at": ds.created_at,
        "finished_at": ds.finished_at,
    }


@router.get("/datasets")
def list_datasets(db: Session = Depends(get_db), _: CurrentUser = Depends(admin)):
    rows = db.scalars(select(DatasetVersion).order_by(DatasetVersion.id.desc())).all()
    emails = dict(db.execute(select(User.id, User.email)).all())
    approved = db.scalar(select(func.count()).select_from(Sample).where(Sample.status == "approved")) or 0
    in_latest = 0
    latest_ready = next((d for d in rows if d.status == "ready"), None)
    if latest_ready:
        in_latest = latest_ready.sample_count
    return {
        "pool": {"approved": approved, "new_since_latest": max(0, approved - in_latest)},
        "items": [_dataset_out(d, emails) for d in rows],
    }


class DatasetIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    val_ratio: float = Field(0.2, ge=0.05, le=0.5)
    notes: str | None = Field(None, max_length=1000)


@router.post("/datasets", status_code=202)
def create_dataset(body: DatasetIn, request: Request, db: Session = Depends(get_db), current: CurrentUser = Depends(admin)):
    if not NAME_RE.match(body.name):
        raise HTTPException(400, detail="Use letters, numbers, dots, dashes or underscores (e.g. ppe-2026-10).")
    if db.scalar(select(DatasetVersion.id).where(DatasetVersion.status == "building")):
        raise HTTPException(409, detail="Another dataset is still being built.")
    ds = DatasetVersion(
        name=body.name,
        val_ratio=body.val_ratio,
        notes=body.notes,
        s3_prefix=f"datasets/{body.name}",
        status="building",
        created_by=current.id,
    )
    db.add(ds)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, detail="A dataset with that name already exists.")
    log_activity(db, request, "Build Dataset", current.id, current.email, body.name)
    dataset_svc.start_build(ds.id)
    return {"id": ds.id, "status": ds.status}


# --- Training runs ------------------------------------------------------------------


class RunIn(BaseModel):
    dataset_version_id: int
    base_model_id: int | None = None  # default: the active model
    epochs: int = Field(80, ge=1, le=1000)
    imgsz: int = Field(1280, ge=320, le=1920, multiple_of=32)
    batch: int = Field(8, ge=1, le=128)
    patience: int = Field(20, ge=0, le=500)
    lr0: float | None = Field(None, gt=0, le=0.1)
    notes: str | None = Field(None, max_length=1000)


def _run_out(run: TrainingRun, db: Session) -> dict:
    ds = db.get(DatasetVersion, run.dataset_version_id)
    base = db.get(ModelVersion, run.base_model_id)
    return {
        "id": run.id,
        "status": run.status,
        "dataset": {"id": ds.id, "name": ds.name} if ds else None,
        "base_model": {"id": base.id, "name": base.name} if base else None,
        "params": run.params,
        "progress": run.progress,
        "metrics": run.metrics,
        "baseline_metrics": run.baseline_metrics,
        "error": run.error,
        "cancel_requested": run.cancel_requested,
        "result_model_id": run.result_model_id,
        "created_by": _email(db, run.created_by),
        "created_at": run.created_at,
        "started_at": run.started_at,
        "finished_at": run.finished_at,
    }


@router.get("/training/runs")
def list_runs(db: Session = Depends(get_db), _: CurrentUser = Depends(admin)):
    runs = db.scalars(select(TrainingRun).order_by(TrainingRun.id.desc()).limit(100)).all()
    return [_run_out(r, db) for r in runs]


@router.get("/training/runs/{run_id}")
def get_run(run_id: int, db: Session = Depends(get_db), _: CurrentUser = Depends(admin)):
    run = db.get(TrainingRun, run_id)
    if run is None:
        raise HTTPException(404, detail="Run not found.")
    return {**_run_out(run, db), "log_tail": run.log_tail}


@router.post("/training/runs", status_code=201)
def start_run(body: RunIn, request: Request, db: Session = Depends(get_db), current: CurrentUser = Depends(admin)):
    ds = db.get(DatasetVersion, body.dataset_version_id)
    if ds is None or ds.status != "ready":
        raise HTTPException(400, detail="Pick a dataset that has finished building.")
    if ds.train_count == 0:
        raise HTTPException(400, detail="This dataset has no training images.")
    base_id = body.base_model_id or get_state(db).active_model_id
    base = db.get(ModelVersion, base_id) if base_id else None
    if base is None:
        raise HTTPException(400, detail="Base model not found.")
    registry = [c.name for c in db.scalars(select(ModelClass).order_by(ModelClass.class_id)).all()]
    if ds.class_names != registry:
        raise HTTPException(
            400, detail="Classes changed since this dataset was built. Build a new dataset version first."
        )
    params = body.model_dump(include={"epochs", "imgsz", "batch", "patience", "lr0"})
    params.update(device="0", workers=4, notes=body.notes)
    run = TrainingRun(
        dataset_version_id=ds.id, base_model_id=base.id, params=params, status="queued", created_by=current.id
    )
    db.add(run)
    db.commit()
    log_activity(
        db,
        request,
        "Start Training",
        current.id,
        current.email,
        f"Run {run.id}: dataset {ds.name}, base {base.name}, {body.epochs} epochs @ {body.imgsz}px. Inference pauses while it runs.",
    )
    return _run_out(run, db)


@router.post("/training/runs/{run_id}/cancel")
def cancel_run(run_id: int, request: Request, db: Session = Depends(get_db), current: CurrentUser = Depends(admin)):
    run = db.get(TrainingRun, run_id)
    if run is None:
        raise HTTPException(404, detail="Run not found.")
    if run.status == "queued":
        run.status = "cancelled"
        run.finished_at = utcnow()
    elif run.status == "running":
        run.cancel_requested = True  # trainer.py stops after the current epoch and resumes inference
    else:
        raise HTTPException(400, detail=f"A {run.status} run can't be cancelled.")
    db.commit()
    log_activity(db, request, "Cancel Training", current.id, current.email, f"Run {run.id}")
    return _run_out(run, db)


# --- Model registry -------------------------------------------------------------------


def _model_out(m: ModelVersion) -> dict:
    return {
        "id": m.id,
        "name": m.name,
        "source": m.source,
        "weights_path": m.weights_path,
        "class_names": m.class_names,
        "metrics": m.metrics,
        "training_run_id": m.training_run_id,
        "is_active": m.is_active,
        "notes": m.notes,
        "created_at": m.created_at,
        "activated_at": m.activated_at,
        "activated_by": m.activated_by,
    }


@router.get("/models")
def list_models(db: Session = Depends(get_db), _: CurrentUser = Depends(admin)):
    return [_model_out(m) for m in db.scalars(select(ModelVersion).order_by(ModelVersion.id.desc())).all()]


class ModelPatch(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=100)
    notes: str | None = Field(None, max_length=1000)


@router.patch("/models/{model_id}")
def update_model(model_id: int, body: ModelPatch, db: Session = Depends(get_db), _: CurrentUser = Depends(admin)):
    model = db.get(ModelVersion, model_id)
    if model is None:
        raise HTTPException(404, detail="Model not found.")
    for k, v in body.model_dump(exclude_unset=True).items():
        setattr(model, k, v)
    db.commit()
    return _model_out(model)


@router.post("/models/{model_id}/activate")
def activate_model(model_id: int, request: Request, db: Session = Depends(get_db), current: CurrentUser = Depends(admin)):
    """Promote (or roll back to) a model. inference.py loads it on its next poll."""
    model = db.get(ModelVersion, model_id)
    if model is None:
        raise HTTPException(404, detail="Model not found.")
    registry = [c.name for c in db.scalars(select(ModelClass).order_by(ModelClass.class_id)).all()]
    names = model.class_names or []
    if names and registry[: len(names)] != names:
        raise HTTPException(400, detail="This model's classes don't match the class registry, so its outputs can't be mapped.")
    previous = db.scalars(select(ModelVersion).where(ModelVersion.is_active.is_(True))).all()
    for m in previous:
        m.is_active = False
    model.is_active = True
    model.activated_at = utcnow()
    model.activated_by = current.email
    state = get_state(db)
    state.active_model_id = model.id
    state.updated_at = utcnow()
    state.updated_by = current.email
    db.commit()
    log_activity(
        db,
        request,
        "Activate Model",
        current.id,
        current.email,
        f"{model.name} (id {model.id}) replaces {', '.join(m.name for m in previous if m.id != model.id) or 'none'}",
    )
    return _model_out(model)
