"""Violations dashboard, notifications dashboard and the Excel export."""
import io
from datetime import date

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import distinct, func, select
from sqlalchemy.orm import Session

from app.core.deps import CurrentUser, require
from app.core.permissions import Permission
from app.db.models import AlertRecipient, Camera, EmailRecord, ModelClass, PpeEvent, ProductionHouse
from app.db.session import get_db
from app.services import analytics
from app.services.audit import log_activity
from app.services.classes import load_registry
from app.services.runtime import get_state, worker_status

router = APIRouter(tags=["dashboard"])
viewer = require(Permission.DASHBOARD_VIEW)
MAX_RANGE_DAYS = 366


class DateRange(BaseModel):
    start_date: date
    end_date: date

    @model_validator(mode="after")
    def check_range(self):
        if self.end_date < self.start_date:
            raise ValueError("end_date must be on or after start_date")
        if (self.end_date - self.start_date).days > MAX_RANGE_DAYS:
            raise ValueError(f"Choose a range of at most {MAX_RANGE_DAYS} days")
        return self


class Filters(DateRange):
    shifts: list[str] = []
    areas: list[str] = []
    production_houses: list[str] = []
    classes: list[str] = []

    def to_event_filters(self) -> analytics.EventFilters:
        return analytics.EventFilters(**self.model_dump(include=set(analytics.EventFilters.__dataclass_fields__)))


class EventsPage(Filters):
    page: int = Field(0, ge=0)
    page_size: int = Field(25, ge=1, le=200)


class NotificationFiltersIn(Filters):
    recipients: list[str] = []


def _enabled_health_ids(db: Session) -> set[str] | None:
    cameras = db.scalars(select(Camera).where(Camera.enabled.is_(True))).all()
    # Before the camera list is imported, fall back to counting everything in camera_health
    return {c.health_id for c in cameras} if cameras else None


@router.post("/dashboard/options")
def options(body: DateRange, db: Session = Depends(get_db), _: CurrentUser = Depends(viewer)):
    def distinct_values(column, date_column):
        stmt = select(distinct(column)).where(date_column >= body.start_date, date_column <= body.end_date)
        return sorted(v for v in db.scalars(stmt).all() if v)

    registry = load_registry(db)
    return {
        "areas": distinct_values(PpeEvent.area, PpeEvent.date1),
        "production_houses": distinct_values(PpeEvent.production_house, PpeEvent.date1),
        "classes": registry.violation_names,
        "shifts": analytics.SHIFTS,
        "recipients": distinct_values(EmailRecord.to_recipients, EmailRecord.insert_date),
    }


@router.post("/dashboard/summary")
def summary(body: Filters, db: Session = Depends(get_db), _: CurrentUser = Depends(viewer)):
    registry = load_registry(db)
    df = analytics.load_events(db, body.to_event_filters(), registry)
    unit, trend = analytics.trend(df, body.start_date, body.end_date)
    health = analytics.camera_health(db, _enabled_health_ids(db))

    false_positives = db.scalar(
        select(func.count(PpeEvent.id)).where(
            PpeEvent.date1 >= body.start_date,
            PpeEvent.date1 <= body.end_date,
            PpeEvent.review_status == "false_positive",
        )
    )
    reviewed = int((df["review_status"] == "confirmed").sum()) if not df.empty else 0

    state = get_state(db)
    workers = worker_status(db)
    inference = workers.get("inference")
    return {
        "metrics": {
            "total_violations": len(df),
            "people_flagged": int(df["violator_count"].fillna(0).sum()) if not df.empty else 0,
            "confirmed": reviewed,
            "false_positives": false_positives or 0,
            "cameras_online": health["online"],
            "cameras_offline": health["offline"],
        },
        "charts": {
            "trend_unit": unit,
            "trend": trend,
            "by_production_house": analytics.counts(df["production_house"]) if not df.empty else [],
            "by_area": analytics.counts(df["area"], limit=20) if not df.empty else [],
            "by_class": analytics.class_counts(df, registry),
            "by_shift": [
                {"name": s, "value": int((df["shift"] == s).sum()) if not df.empty else 0} for s in analytics.SHIFTS
            ],
        },
        "camera_health": health,
        "system": {
            "inference_paused": state.inference_paused,
            "pause_reason": state.pause_reason,
            "inference_online": bool(inference and inference["online"]),
        },
    }


def _event_row(r) -> dict:
    return {
        "id": int(r.id),
        "date": r.date1.isoformat(),
        "time": r.time1.strftime("%H:%M:%S"),
        "shift": r.shift,
        "production_house": r.production_house,
        "area": r.area,
        "classes": list(r.classes),
        "people_count": int(r.people_count) if pd.notna(r.people_count) else None,
        "violator_count": int(r.violator_count) if pd.notna(r.violator_count) else None,
        "review_status": r.review_status if isinstance(r.review_status, str) else None,
        "has_clean_frame": isinstance(r.raw_image_key, str) and bool(r.raw_image_key),
    }


@router.post("/dashboard/events")
def events(body: EventsPage, db: Session = Depends(get_db), _: CurrentUser = Depends(viewer)):
    df = analytics.load_events(db, body.to_event_filters(), load_registry(db))
    start = body.page * body.page_size
    page = df.iloc[start : start + body.page_size]
    return {"items": [_event_row(r) for r in page.itertuples()], "total": len(df)}


@router.post("/dashboard/export")
def export_excel(
    body: Filters, request: Request, db: Session = Depends(get_db), current: CurrentUser = Depends(viewer)
):
    registry = load_registry(db)
    df = analytics.load_events(db, body.to_event_filters(), registry)
    if df.empty:
        raise HTTPException(404, detail="No violations match these filters.")
    df = analytics.dedupe_5min_buckets(df)
    health = analytics.camera_health(db, _enabled_health_ids(db))

    raw = pd.DataFrame(
        {
            "ID": df["id"],
            "Date": df["date1"].astype(str),
            "Time": df["time1"].astype(str),
            "Shift": df["shift"],
            "Production house": df["production_house"],
            "Area": df["area"],
            "Violations": df["classes"].map(", ".join),
            "People": df["people_count"],
            "Violators": df["violator_count"],
            "Review": df["review_status"].fillna("Not reviewed"),
            "Image URL": df["image_url"],
        }
    )
    sheets = {
        "Raw Data": raw,
        "Summary": pd.DataFrame(
            [
                ["Total violations", len(df)],
                ["Cameras online", health["online"]],
                ["Cameras offline", health["offline"]],
            ],
            columns=["Metric", "Value"],
        ),
        "By Production House": pd.DataFrame(
            [(x["name"], x["value"]) for x in analytics.counts(df["production_house"])], columns=["Production house", "Count"]
        ),
        "By Area": pd.DataFrame([(x["name"], x["value"]) for x in analytics.counts(df["area"])], columns=["Area", "Count"]),
        "By Class": pd.DataFrame(
            [(x["name"], x["value"]) for x in analytics.class_counts(df, registry)], columns=["Violation class", "Count"]
        ),
    }
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="xlsxwriter") as writer:
        for name, frame in sheets.items():
            frame.to_excel(writer, index=False, sheet_name=name)
            writer.sheets[name].autofit()
    buffer.seek(0)

    log_activity(db, request, "Export Excel", current.id, current.email, f"{body.start_date} to {body.end_date}, {len(df)} rows")
    filename = f"PPE_Report_{body.start_date}_to_{body.end_date}.xlsx"
    return StreamingResponse(
        buffer,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/notifications/summary")
def notifications(body: NotificationFiltersIn, db: Session = Depends(get_db), _: CurrentUser = Depends(viewer)):
    registry = load_registry(db)
    f = analytics.NotificationFilters(**body.model_dump(include=set(analytics.NotificationFilters.__dataclass_fields__)))
    df = analytics.load_notifications(db, f, registry)

    # Supervisor titles now live on the alert recipients (was a hard-coded map in app.py)
    designations = {
        r.email.lower(): r.designation
        for r in db.scalars(select(AlertRecipient).where(AlertRecipient.designation.is_not(None))).all()
    }

    def top(series: pd.Series) -> dict:
        vc = series.dropna().value_counts()
        return {"name": str(vc.index[0]), "count": int(vc.iloc[0])} if not vc.empty else {"name": None, "count": 0}

    tree = []
    if not df.empty:
        for (email, name), group in df.groupby(["recipient_email", "recipient"], sort=False):
            houses = []
            for ph, ph_group in group.groupby("production_house", sort=False):
                houses.append(
                    {"name": ph, "count": len(ph_group), "areas": analytics.counts(ph_group["area"])}
                )
            houses.sort(key=lambda h: -h["count"])
            tree.append(
                {
                    "name": name,
                    "email": email,
                    "designation": designations.get(email or ""),
                    "count": len(group),
                    "production_houses": houses,
                }
            )
        tree.sort(key=lambda t: -t["count"])

    return {
        "metrics": {
            "total": len(df),
            "top_recipient": top(df["recipient"]) if not df.empty else top(pd.Series(dtype=str)),
            "top_class": top(df["classes"].explode()) if not df.empty else top(pd.Series(dtype=str)),
            "top_production_house": top(df["production_house"]) if not df.empty else top(pd.Series(dtype=str)),
        },
        "charts": {
            "by_recipient": analytics.counts(df["recipient"]) if not df.empty else [],
            "by_production_house": analytics.counts(df["production_house"]) if not df.empty else [],
            "by_class": analytics.class_counts(df, registry),
        },
        "tree": tree,
    }


@router.get("/classes")
def classes(db: Session = Depends(get_db), _: CurrentUser = Depends(viewer)):
    """The class registry in YOLO index order (for the annotation and review screens)."""
    return [
        {"class_id": c.class_id, "name": c.name, "is_violation": c.is_violation, "enabled": c.enabled}
        for c in db.scalars(select(ModelClass).order_by(ModelClass.class_id)).all()
    ]


@router.get("/dashboard/production-houses")
def configured_production_houses(db: Session = Depends(get_db), _: CurrentUser = Depends(viewer)):
    """Configured houses and areas (for filter pickers before any events exist)."""
    rows = db.execute(
        select(ProductionHouse.name, Camera.area).join(Camera, Camera.production_house_id == ProductionHouse.id)
    ).all()
    houses: dict[str, list[str]] = {}
    for ph, area in rows:
        houses.setdefault(ph, []).append(area)
    return [{"name": k, "areas": sorted(v)} for k, v in sorted(houses.items())]
