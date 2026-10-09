"""Dashboard and notification analytics, ported from the Flask app.py.

Same business rules as before: shift windows, the 5-minute de-duplication per
(area, class), the camera health counts. Queries are parameterised now.
"""
from dataclasses import dataclass, field
from datetime import date, datetime, time

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import CameraHealth, EmailRecord, PpeEvent
from app.services.classes import Registry

SHIFTS = ["Shift A", "Shift B", "Shift C"]
DEDUP_SECONDS = 300


def shift_of(t: time) -> str:
    """A 06:00-14:29:59, B 14:30-22:59:59, C 23:00-05:59:59."""
    if time(6, 0) <= t < time(14, 30):
        return "Shift A"
    if time(14, 30) <= t < time(23, 0):
        return "Shift B"
    return "Shift C"


@dataclass
class EventFilters:
    start_date: date
    end_date: date
    shifts: list[str] = field(default_factory=list)
    areas: list[str] = field(default_factory=list)
    production_houses: list[str] = field(default_factory=list)
    classes: list[str] = field(default_factory=list)


EVENT_COLUMNS = [
    "id",
    "date1",
    "time1",
    "production_house",
    "area",
    "class1",
    "image_url",
    "camera_status",
    "people_count",
    "violator_count",
    "review_status",
    "raw_image_key",
]


def load_events(db: Session, f: EventFilters, registry: Registry) -> pd.DataFrame:
    """Violation events after filters and de-duplication, newest first.
    Rows marked false positive (violation = false) are excluded, as before."""
    stmt = select(*(getattr(PpeEvent, c) for c in EVENT_COLUMNS)).where(
        PpeEvent.date1 >= f.start_date,
        PpeEvent.date1 <= f.end_date,
        PpeEvent.violation.is_(True),
    )
    if f.areas:
        stmt = stmt.where(PpeEvent.area.in_(f.areas))
    if f.production_houses:
        stmt = stmt.where(PpeEvent.production_house.in_(f.production_houses))
    rows = db.execute(stmt).all()
    df = pd.DataFrame(rows, columns=EVENT_COLUMNS)
    if df.empty:
        return _with_derived(df)

    df = df[df["time1"].notna() & df["date1"].notna()].copy()
    df["shift"] = df["time1"].map(shift_of)
    if f.shifts:
        df = df[df["shift"].isin(f.shifts)]
    df["classes"] = df["class1"].map(registry.violations_in)
    if f.classes:
        wanted = set(f.classes)
        df = df[df["classes"].map(lambda cs: bool(wanted.intersection(cs)))]
    df["ts"] = [datetime.combine(d, t) for d, t in zip(df["date1"], df["time1"])]
    df = _dedupe(df)
    return df.sort_values("ts", ascending=False).reset_index(drop=True)


def _with_derived(df: pd.DataFrame) -> pd.DataFrame:
    for col, dtype in (("shift", "object"), ("classes", "object"), ("ts", "datetime64[ns]")):
        df[col] = pd.Series(dtype=dtype)
    return df


def _dedupe(df: pd.DataFrame) -> pd.DataFrame:
    """For each (area, class string) keep an event only if >= 5 min after the last kept one."""
    if df.empty:
        return df
    df = df.sort_values("ts")
    keep = []
    last_seen: dict[tuple, datetime] = {}
    for idx, area, cls, ts in zip(df.index, df["area"], df["class1"], df["ts"]):
        key = (area, cls)
        prev = last_seen.get(key)
        if prev is None or (ts - prev).total_seconds() >= DEDUP_SECONDS:
            last_seen[key] = ts
            keep.append(idx)
    return df.loc[keep]


def dedupe_5min_buckets(df: pd.DataFrame) -> pd.DataFrame:
    """Extra de-duplication the Excel export applied: one row per area/house/class per 5-minute bucket."""
    if df.empty:
        return df
    bucket = df["ts"].dt.floor("5min")
    return df.assign(_bucket=bucket).drop_duplicates(["area", "production_house", "class1", "_bucket"]).drop(columns="_bucket")


def counts(series: pd.Series, limit: int | None = None) -> list[dict]:
    vc = series.dropna().value_counts()
    if limit:
        vc = vc.head(limit)
    return [{"name": str(k), "value": int(v)} for k, v in vc.items()]


def class_counts(df: pd.DataFrame, registry: Registry) -> list[dict]:
    tally = {name: 0 for name in registry.violation_names}
    for classes in df["classes"] if not df.empty else []:
        for c in classes:
            tally[c] += 1
    return [{"name": k, "value": v} for k, v in tally.items()]


def trend(df: pd.DataFrame, start: date, end: date) -> tuple[str, list[dict]]:
    """Hourly for ranges up to two days, daily otherwise. Empty buckets are filled with 0."""
    unit = "hour" if (end - start).days <= 1 else "day"
    freq = "h" if unit == "hour" else "D"
    index = pd.date_range(
        datetime.combine(start, time.min), datetime.combine(end, time(23, 0) if unit == "hour" else time.min), freq=freq
    )
    if df.empty:
        series = pd.Series(0, index=index)
    else:
        series = df.groupby(df["ts"].dt.floor(freq)).size().reindex(index, fill_value=0)
    return unit, [{"t": ts.isoformat(), "value": int(v)} for ts, v in series.items()]


def camera_health(db: Session, enabled_health_ids: set[str] | None) -> dict:
    """Online/offline counts and the offline list. When the camera config is in the DB,
    only cameras that are currently enabled are counted."""
    rows = db.scalars(select(CameraHealth)).all()
    if enabled_health_ids is not None:
        rows = [r for r in rows if r.camera_id in enabled_health_ids]
    online = [r for r in rows if r.status]
    offline = sorted((r for r in rows if r.status is False), key=lambda r: (r.production_house or "", r.area or ""))
    by_ph: dict[str, int] = {}
    for r in offline:
        by_ph[r.production_house or "Unknown"] = by_ph.get(r.production_house or "Unknown", 0) + 1
    return {
        "online": len(online),
        "offline": len(offline),
        "offline_by_production_house": [
            {"name": k, "value": v} for k, v in sorted(by_ph.items(), key=lambda kv: (-kv[1], kv[0]))
        ],
        "offline_cameras": [
            {
                "plant": r.plant,
                "production_house": r.production_house,
                "area": r.area,
                "last_checked": r.last_checked.isoformat() if r.last_checked else None,
            }
            for r in offline
        ],
    }


# --- Notifications ------------------------------------------------------------------


def name_from_email(value: str | None) -> str:
    """'first.last@x, other@y' -> 'First Last' (first recipient), as the Flask app did."""
    if not value:
        return ""
    first = value.split(",")[0].strip()
    local = first.split("@")[0]
    return " ".join(p.capitalize() for p in local.replace("_", ".").split(".") if p)


def first_email(value: str | None) -> str | None:
    if not value:
        return None
    return value.split(",")[0].strip().lower() or None


@dataclass
class NotificationFilters(EventFilters):
    recipients: list[str] = field(default_factory=list)


def load_notifications(db: Session, f: NotificationFilters, registry: Registry) -> pd.DataFrame:
    cols = ["id", "class_label", "production_house", "area", "to_recipients", "cc_recipients", "insert_date", "insert_time"]
    stmt = select(*(getattr(EmailRecord, c) for c in cols)).where(
        EmailRecord.insert_date >= f.start_date, EmailRecord.insert_date <= f.end_date
    )
    if f.areas:
        stmt = stmt.where(EmailRecord.area.in_(f.areas))
    if f.production_houses:
        stmt = stmt.where(EmailRecord.production_house.in_(f.production_houses))
    if f.recipients:
        stmt = stmt.where(EmailRecord.to_recipients.in_(f.recipients))
    df = pd.DataFrame(db.execute(stmt).all(), columns=cols)
    if df.empty:
        return df.assign(shift=pd.Series(dtype="object"), classes=pd.Series(dtype="object"))
    df = df[df["insert_time"].notna()].copy()
    df["shift"] = df["insert_time"].map(shift_of)
    if f.shifts:
        df = df[df["shift"].isin(f.shifts)]
    df["classes"] = df["class_label"].map(registry.violations_in)
    if f.classes:
        wanted = set(f.classes)
        df = df[df["classes"].map(lambda cs: bool(wanted.intersection(cs)))]
    df["recipient"] = df["to_recipients"].map(name_from_email)
    df["recipient_email"] = df["to_recipients"].map(first_email)
    return df.sort_values(["insert_date", "insert_time"], ascending=False)
