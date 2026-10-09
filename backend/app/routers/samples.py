"""Annotation: uploads, camera snapshots, labelling, QA approval into the training pool."""
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.deps import CurrentUser, get_current_user, require
from app.core.permissions import Permission
from app.core.security import utcnow
from app.db.models import Camera, ModelClass, Sample, SampleLabel, User
from app.db.session import get_db
from app.routers.events import image_response
from app.schemas.labels import LabelsIn
from app.services import samples as sample_svc
from app.services import vision
from app.services.audit import log_activity
from app.services.storage import ObjectNotFound, get_bytes_any, get_storage

router = APIRouter(prefix="/samples", tags=["samples"])
annotator = require(Permission.ANNOTATIONS_CREATE)
approver = require(Permission.ANNOTATIONS_APPROVE)

Status = Literal["draft", "submitted", "approved", "rejected"]
EDITABLE_BY_ANNOTATOR = {"draft", "submitted", "rejected"}


def can_see_samples(current: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    if not (
        current.has(Permission.ANNOTATIONS_CREATE)
        or current.has(Permission.ANNOTATIONS_APPROVE)
        or current.has(Permission.VIOLATIONS_REVIEW)
    ):
        raise HTTPException(403, detail="Missing permission: annotations.create")
    return current


def _get(db: Session, sample_id: int) -> Sample:
    sample = db.get(Sample, sample_id)
    if sample is None:
        raise HTTPException(404, detail="Sample not found.")
    return sample


def _labels_out(sample: Sample) -> list[dict]:
    return [
        {"class_id": lb.class_id, "cx": lb.cx, "cy": lb.cy, "w": lb.w, "h": lb.h, "origin": lb.origin, "conf": lb.conf}
        for lb in sample.labels
    ]


def _summary(sample: Sample, emails: dict[int, str]) -> dict:
    return {
        "id": sample.id,
        "status": sample.status,
        "source": sample.source,
        "production_house": sample.production_house,
        "area": sample.area,
        "ppes_id": sample.ppes_id,
        "width": sample.width,
        "height": sample.height,
        "label_count": len(sample.labels),
        "class_ids": sorted({lb.class_id for lb in sample.labels}),
        "created_by": emails.get(sample.created_by or 0),
        "created_at": sample.created_at,
        "updated_at": sample.updated_at,
        "reject_reason": sample.reject_reason,
    }


def _emails(db: Session, ids: set[int | None]) -> dict[int, str]:
    ids = {i for i in ids if i}
    if not ids:
        return {}
    return dict(db.execute(select(User.id, User.email).where(User.id.in_(ids))).all())


@router.get("")
def list_samples(
    status: Status | None = None,
    source: Literal["review", "upload", "snapshot"] | None = None,
    class_id: int | None = None,
    mine: bool = False,
    q: str | None = Query(None, max_length=100),
    page: int = Query(0, ge=0),
    page_size: int = Query(48, ge=1, le=200),
    db: Session = Depends(get_db),
    current: CurrentUser = Depends(can_see_samples),
):
    stmt = select(Sample)
    if status:
        stmt = stmt.where(Sample.status == status)
    if source:
        stmt = stmt.where(Sample.source == source)
    if mine:
        stmt = stmt.where(Sample.created_by == current.id)
    if class_id is not None:
        stmt = stmt.where(Sample.id.in_(select(SampleLabel.sample_id).where(SampleLabel.class_id == class_id)))
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(Sample.production_house.ilike(like), Sample.area.ilike(like)))
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(stmt.order_by(Sample.id.desc()).limit(page_size).offset(page * page_size)).all()
    emails = _emails(db, {s.created_by for s in rows})
    return {"total": total, "items": [_summary(s, emails) for s in rows]}


@router.get("/stats")
def stats(db: Session = Depends(get_db), _: CurrentUser = Depends(can_see_samples)):
    """Status counts plus per-class instances, so annotators can see which classes are short."""
    status_counts = dict(db.execute(select(Sample.status, func.count()).group_by(Sample.status)).all())

    def per_class(statuses: list[str]):
        rows = db.execute(
            select(SampleLabel.class_id, func.count(), func.count(func.distinct(SampleLabel.sample_id)))
            .join(Sample, Sample.id == SampleLabel.sample_id)
            .where(Sample.status.in_(statuses))
            .group_by(SampleLabel.class_id)
        ).all()
        return {cid: {"instances": n, "images": imgs} for cid, n, imgs in rows}

    approved = per_class(["approved"])
    pending = per_class(["draft", "submitted"])
    background = db.scalar(
        select(func.count()).select_from(Sample).where(Sample.status == "approved", ~Sample.labels.any())
    )
    classes = db.scalars(select(ModelClass).order_by(ModelClass.class_id)).all()
    return {
        "status_counts": {s: status_counts.get(s, 0) for s in ("draft", "submitted", "approved", "rejected")},
        "background_images": background or 0,
        "classes": [
            {
                "class_id": c.class_id,
                "name": c.name,
                "is_violation": c.is_violation,
                "enabled": c.enabled,
                "approved_instances": approved.get(c.class_id, {}).get("instances", 0),
                "approved_images": approved.get(c.class_id, {}).get("images", 0),
                "pending_instances": pending.get(c.class_id, {}).get("instances", 0),
            }
            for c in classes
        ],
    }


def _new_sample(db: Session, stored: sample_svc.StoredImage, source: str, current: CurrentUser, **kw) -> Sample:
    sample = Sample(
        image_key=stored.key,
        width=stored.width,
        height=stored.height,
        image_sha1=stored.sha1,
        source=source,
        status="draft",
        created_by=current.id,
        **kw,
    )
    db.add(sample)
    return sample


@router.post("/upload", status_code=201)
async def upload(
    request: Request,
    files: list[UploadFile] = File(...),
    production_house: str | None = Form(None),
    area: str | None = Form(None),
    db: Session = Depends(get_db),
    current: CurrentUser = Depends(annotator),
):
    settings = get_settings()
    limit = settings.max_upload_mb * 1024 * 1024
    storage = get_storage()
    created, skipped = [], []
    for upload_file in files[:100]:
        data = await upload_file.read(limit + 1)
        if len(data) > limit:
            skipped.append({"file": upload_file.filename, "reason": f"Larger than {settings.max_upload_mb} MB"})
            continue
        try:
            stored = sample_svc.store_image(storage, data)
        except sample_svc.InvalidImage as e:
            skipped.append({"file": upload_file.filename, "reason": str(e)})
            continue
        duplicate = db.scalar(select(Sample.id).where(Sample.image_sha1 == stored.sha1))
        if duplicate:
            storage.delete(stored.key)
            skipped.append({"file": upload_file.filename, "reason": f"Already uploaded as sample #{duplicate}"})
            continue
        sample = _new_sample(db, stored, "upload", current, production_house=production_house, area=area)
        db.flush()
        created.append(sample.id)
    db.commit()
    if created:
        log_activity(db, request, "Upload Samples", current.id, current.email, f"{len(created)} images uploaded")
    return {"created": created, "skipped": skipped}


class SnapshotIn(BaseModel):
    camera_id: int


@router.post("/snapshot", status_code=201)
def snapshot(body: SnapshotIn, request: Request, db: Session = Depends(get_db), current: CurrentUser = Depends(annotator)):
    camera = db.get(Camera, body.camera_id)
    if camera is None:
        raise HTTPException(404, detail="Camera not found.")
    try:
        jpeg = vision.grab_frame(camera.stream_url)
    except vision.SnapshotError as e:
        raise HTTPException(502, detail=str(e))
    stored = sample_svc.store_image(get_storage(), jpeg)
    sample = _new_sample(
        db,
        stored,
        "snapshot",
        current,
        camera_id=camera.id,
        production_house=camera.production_house.name,
        area=camera.area,
    )
    db.commit()
    log_activity(
        db, request, "Camera Snapshot", current.id, current.email, f"{camera.production_house.name} / {camera.area}"
    )
    return {"id": sample.id}


@router.get("/{sample_id}")
def get_sample(
    sample_id: int,
    status: Status | None = None,
    db: Session = Depends(get_db),
    _: CurrentUser = Depends(can_see_samples),
):
    sample = _get(db, sample_id)
    emails = _emails(db, {sample.created_by, sample.approved_by})
    queue = select(Sample.id).where(Sample.status == (status or sample.status))
    next_id = db.scalar(queue.where(Sample.id < sample.id).order_by(Sample.id.desc()).limit(1))
    prev_id = db.scalar(queue.where(Sample.id > sample.id).order_by(Sample.id.asc()).limit(1))
    return {
        **_summary(sample, emails),
        "labels": _labels_out(sample),
        "notes": sample.notes,
        "approved_by": emails.get(sample.approved_by or 0),
        "approved_at": sample.approved_at,
        "next_id": next_id,
        "prev_id": prev_id,
    }


@router.get("/{sample_id}/image")
def sample_image(sample_id: int, db: Session = Depends(get_db), _: CurrentUser = Depends(can_see_samples)):
    return image_response(_get(db, sample_id).image_key)


def _check_editable(sample: Sample, current: CurrentUser) -> None:
    if current.has(Permission.ANNOTATIONS_APPROVE):
        return
    if not current.has(Permission.ANNOTATIONS_CREATE) or sample.status not in EDITABLE_BY_ANNOTATOR:
        raise HTTPException(403, detail="Approved samples can only be changed by an approver.")


@router.put("/{sample_id}/labels")
def save_labels(
    sample_id: int,
    body: LabelsIn,
    request: Request,
    db: Session = Depends(get_db),
    current: CurrentUser = Depends(can_see_samples),
):
    sample = _get(db, sample_id)
    _check_editable(sample, current)
    try:
        sample_svc.replace_labels(db, sample, [lb.model_dump() for lb in body.labels])
    except ValueError as e:
        raise HTTPException(400, detail=str(e))
    if sample.status == "rejected":
        sample.status = "draft"
    db.flush()
    if sample.status == "approved":
        sample_svc.write_to_pool(get_storage(), sample)  # keep the pool's .txt in step
    db.commit()
    return {"id": sample.id, "status": sample.status, "labels": _labels_out(sample)}


@router.post("/{sample_id}/suggest")
def suggest(sample_id: int, db: Session = Depends(get_db), _: CurrentUser = Depends(annotator)):
    sample = _get(db, sample_id)
    try:
        data = get_bytes_any(sample.image_key)
    except ObjectNotFound:
        raise HTTPException(404, detail="Image not found in storage.")
    try:
        return {"labels": vision.suggest_labels(db, data)}
    except vision.PrelabelUnavailable as e:
        raise HTTPException(501, detail=str(e))


@router.post("/{sample_id}/submit")
def submit(sample_id: int, request: Request, db: Session = Depends(get_db), current: CurrentUser = Depends(annotator)):
    sample = _get(db, sample_id)
    if sample.status not in ("draft", "rejected"):
        raise HTTPException(400, detail=f"A {sample.status} sample can't be submitted.")
    sample.status = "submitted"
    sample.submitted_at = utcnow()
    sample.reject_reason = None
    db.commit()
    return {"id": sample.id, "status": sample.status}


@router.post("/{sample_id}/approve")
def approve(sample_id: int, request: Request, db: Session = Depends(get_db), current: CurrentUser = Depends(approver)):
    sample = _get(db, sample_id)
    sample.status = "approved"
    sample.approved_by = current.id
    sample.approved_at = utcnow()
    sample.reject_reason = None
    db.flush()
    sample_svc.write_to_pool(get_storage(), sample)
    db.commit()
    log_activity(db, request, "Approve Sample", current.id, current.email, f"Sample {sample.id}, {len(sample.labels)} boxes")
    return {"id": sample.id, "status": sample.status}


class RejectIn(BaseModel):
    reason: str = Field(min_length=1, max_length=500)


@router.post("/{sample_id}/reject")
def reject(
    sample_id: int, body: RejectIn, request: Request, db: Session = Depends(get_db), current: CurrentUser = Depends(approver)
):
    sample = _get(db, sample_id)
    was_approved = sample.status == "approved"
    sample.status = "rejected"
    sample.reject_reason = body.reason
    sample.approved_by = None
    sample.approved_at = None
    db.commit()
    if was_approved:
        sample_svc.remove_from_pool(get_storage(), sample.id)
    log_activity(db, request, "Reject Sample", current.id, current.email, f"Sample {sample.id}: {body.reason}")
    return {"id": sample.id, "status": sample.status}


@router.delete("/{sample_id}", status_code=204)
def delete_sample(
    sample_id: int, request: Request, db: Session = Depends(get_db), current: CurrentUser = Depends(can_see_samples)
):
    sample = _get(db, sample_id)
    own_draft = sample.created_by == current.id and sample.status in ("draft", "rejected")
    if not (own_draft or current.has(Permission.ANNOTATIONS_APPROVE)):
        raise HTTPException(403, detail="Only approvers can delete other people's or submitted samples.")
    storage = get_storage()
    sample_svc.remove_from_pool(storage, sample.id)
    if sample.source in ("upload", "snapshot"):
        storage.delete(sample.image_key)  # review samples share the event's clean frame; keep it
    db.delete(sample)
    db.commit()
    log_activity(db, request, "Delete Sample", current.id, current.email, f"Sample {sample_id}")
