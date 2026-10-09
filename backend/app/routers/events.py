"""Detection events: detail, images, and the review workflow (false positives -> training data)."""
from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.deps import CurrentUser, require
from app.core.permissions import Permission
from app.core.security import utcnow
from app.db.models import ModelClass, PpeEvent, Sample, User
from app.db.session import get_db
from app.schemas.labels import Label
from app.services import samples as sample_svc
from app.services.audit import log_activity
from app.services.classes import load_registry
from app.services.storage import ObjectNotFound, StorageError, get_storage, key_from_image_url, stream_any

router = APIRouter(prefix="/events", tags=["events"])
viewer = require(Permission.DASHBOARD_VIEW)
reviewer = require(Permission.VIOLATIONS_REVIEW)

DEFAULT_FRAME = (1920, 1080)
ReviewStatus = Literal["unreviewed", "confirmed", "false_positive", "all"]


def _get_event(db: Session, event_id: int) -> PpeEvent:
    event = db.get(PpeEvent, event_id)
    if event is None:
        raise HTTPException(404, detail="Event not found.")
    return event


def image_response(key: str | None) -> StreamingResponse:
    if not key:
        raise HTTPException(404, detail="No image stored for this item.")
    try:
        chunks = stream_any(key)
    except ObjectNotFound:
        raise HTTPException(404, detail="Image not found in storage.")
    except StorageError as e:
        raise HTTPException(502, detail=f"Storage error: {e}")
    return StreamingResponse(chunks, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=86400"})


@router.get("/{event_id}/image")
def event_image(
    event_id: int,
    variant: Literal["annotated", "raw"] = "annotated",
    db: Session = Depends(get_db),
    _: CurrentUser = Depends(viewer),
):
    event = _get_event(db, event_id)
    key = event.raw_image_key if variant == "raw" else key_from_image_url(event.image_url)
    return image_response(key)


def _split_detections(event: PpeEvent, thresholds: dict[int, float]) -> tuple[list[dict], list[dict]]:
    """Model boxes as normalised labels: those at or above the class threshold pre-fill the
    editor; weaker ones are offered as suggestions the reviewer can accept."""
    width = event.frame_width or DEFAULT_FRAME[0]
    height = event.frame_height or DEFAULT_FRAME[1]
    prefill, suggestions = [], []
    for det in event.detections or []:
        class_id = det.get("class_id")
        box = sample_svc.pixel_box_to_yolo(det.get("box") or [0, 0, 0, 0], width, height)
        if class_id not in thresholds or box is None:
            continue
        cx, cy, w, h = box
        label = {"class_id": class_id, "cx": cx, "cy": cy, "w": w, "h": h, "origin": "model", "conf": det.get("conf")}
        (prefill if (det.get("conf") or 0) >= thresholds[class_id] else suggestions).append(label)
    return prefill, suggestions


@router.get("")
def review_queue(
    status: ReviewStatus = "unreviewed",
    start_date: date | None = None,
    end_date: date | None = None,
    production_house: str | None = None,
    area: str | None = None,
    clean_frame_only: bool = False,
    page: int = Query(0, ge=0),
    page_size: int = Query(30, ge=1, le=100),
    db: Session = Depends(get_db),
    _: CurrentUser = Depends(reviewer),
):
    stmt = select(PpeEvent)
    if status == "unreviewed":
        stmt = stmt.where(PpeEvent.review_status.is_(None), PpeEvent.violation.is_not(False))
    elif status != "all":
        stmt = stmt.where(PpeEvent.review_status == status)
    if start_date:
        stmt = stmt.where(PpeEvent.date1 >= start_date)
    if end_date:
        stmt = stmt.where(PpeEvent.date1 <= end_date)
    if production_house:
        stmt = stmt.where(PpeEvent.production_house == production_house)
    if area:
        stmt = stmt.where(PpeEvent.area == area)
    if clean_frame_only:
        stmt = stmt.where(PpeEvent.raw_image_key.is_not(None))

    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(stmt.order_by(PpeEvent.id.desc()).limit(page_size).offset(page * page_size)).all()
    registry = load_registry(db)
    return {
        "total": total,
        "items": [
            {
                "id": e.id,
                "date": e.date1.isoformat() if e.date1 else None,
                "time": e.time1.strftime("%H:%M:%S") if e.time1 else None,
                "production_house": e.production_house,
                "area": e.area,
                "classes": registry.violations_in(e.class1),
                "review_status": e.review_status,
                "has_clean_frame": bool(e.raw_image_key),
            }
            for e in rows
        ],
    }


@router.get("/{event_id}")
def event_detail(event_id: int, db: Session = Depends(get_db), _: CurrentUser = Depends(viewer)):
    event = _get_event(db, event_id)
    registry = load_registry(db)
    thresholds = {c.class_id: c.threshold for c in db.scalars(select(ModelClass)).all()}
    prefill, suggestions = _split_detections(event, thresholds)
    sample = db.scalar(select(Sample).where(Sample.ppes_id == event.id))
    reviewer_email = db.get(User, event.reviewed_by).email if event.reviewed_by else None

    # Neighbouring unreviewed events, for "next" in the review screen
    next_id = db.scalar(
        select(PpeEvent.id)
        .where(PpeEvent.id < event.id, PpeEvent.review_status.is_(None), PpeEvent.violation.is_not(False))
        .order_by(PpeEvent.id.desc())
        .limit(1)
    )
    return {
        "id": event.id,
        "date": event.date1.isoformat() if event.date1 else None,
        "time": event.time1.strftime("%H:%M:%S") if event.time1 else None,
        "production_house": event.production_house,
        "area": event.area,
        "camera_id": event.camera_id,
        "classes": registry.violations_in(event.class1),
        "compliance": event.compliance,
        "required_ppes": event.required_ppes,
        "people_count": event.people_count,
        "violator_count": event.violator_count,
        "has_clean_frame": bool(event.raw_image_key),
        "frame": {"width": event.frame_width or DEFAULT_FRAME[0], "height": event.frame_height or DEFAULT_FRAME[1]},
        "review": {
            "status": event.review_status,
            "by": reviewer_email,
            "at": event.reviewed_at,
            "notes": event.review_notes,
        },
        "labels": [
            {"class_id": lb.class_id, "cx": lb.cx, "cy": lb.cy, "w": lb.w, "h": lb.h, "origin": lb.origin, "conf": lb.conf}
            for lb in sample.labels
        ]
        if sample
        else prefill,
        "suggestions": suggestions,
        "sample": {"id": sample.id, "status": sample.status} if sample else None,
        "next_unreviewed_id": next_id,
    }


class ReviewIn(BaseModel):
    verdict: Literal["confirmed", "false_positive"]
    notes: str | None = Field(None, max_length=2000)
    # Full set of boxes for the frame; None = verdict only, nothing saved for training
    labels: list[Label] | None = Field(None, max_length=500)
    approve: bool = False


@router.post("/{event_id}/review")
def review_event(
    event_id: int,
    body: ReviewIn,
    request: Request,
    db: Session = Depends(get_db),
    current: CurrentUser = Depends(reviewer),
):
    event = _get_event(db, event_id)
    event.review_status = body.verdict
    # violation=false is what the dashboards (old and new) and cooldown.py filter on
    event.violation = body.verdict != "false_positive"
    event.reviewed_by = current.id
    event.reviewed_at = utcnow()
    event.review_notes = body.notes

    sample_info = None
    if body.labels is not None:
        if not event.raw_image_key:
            raise HTTPException(
                400,
                detail="This event has no clean frame (it was recorded before v2), so it can't be used for training.",
            )
        storage = get_storage()
        sample = db.scalar(select(Sample).where(Sample.ppes_id == event.id))
        was_approved = bool(sample and sample.status == "approved")
        if sample is None:
            sample = Sample(
                image_key=event.raw_image_key,
                width=event.frame_width or DEFAULT_FRAME[0],
                height=event.frame_height or DEFAULT_FRAME[1],
                source="review",
                ppes_id=event.id,
                camera_id=event.camera_id,
                production_house=event.production_house,
                area=event.area,
                created_by=current.id,
            )
            db.add(sample)
        try:
            sample_svc.replace_labels(db, sample, [lb.model_dump() for lb in body.labels])
        except ValueError as e:
            raise HTTPException(400, detail=str(e))

        approve = body.approve and current.has(Permission.ANNOTATIONS_APPROVE)
        now = utcnow()
        sample.submitted_at = now
        sample.reject_reason = None
        if approve:
            sample.status, sample.approved_by, sample.approved_at = "approved", current.id, now
        else:
            sample.status, sample.approved_by, sample.approved_at = "submitted", None, None
        db.flush()
        if approve:
            sample_svc.write_to_pool(storage, sample)
        elif was_approved:
            sample_svc.remove_from_pool(storage, sample.id)
        sample_info = {"id": sample.id, "status": sample.status, "labels": len(sample.labels)}

    db.commit()
    detail = f"Event {event.id} ({event.production_house} / {event.area}): {body.verdict}"
    if sample_info:
        detail += f"; sample {sample_info['id']} {sample_info['status']} with {sample_info['labels']} boxes"
    log_activity(db, request, "Review Event", current.id, current.email, detail)
    return {"id": event.id, "review_status": event.review_status, "sample": sample_info}
