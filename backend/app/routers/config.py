"""Plant configuration: plants, production houses, cameras, PPE rules, classes, recipients.

Every write bumps runtime_state.config_version; inference.py picks the change up on its
next poll (about 30 s) without a restart.
"""
import json
import re
from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, Response, UploadFile
from pydantic import AfterValidator, BaseModel, EmailStr, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.deps import CurrentUser, get_current_user, require
from app.core.permissions import Permission
from app.db.models import (
    AlertRecipient,
    Camera,
    CameraHealth,
    ModelClass,
    ModelVersion,
    Plant,
    PpeItem,
    ProductionHouse,
)
from app.db.session import get_db
from app.services import config_io, vision
from app.services.audit import log_activity
from app.services.runtime import bump_config_version, get_state

router = APIRouter(prefix="/config", tags=["config"])
cameras_perm = require(Permission.CONFIG_CAMERAS)
ppe_perm = require(Permission.CONFIG_PPE)
recipients_perm = require(Permission.CONFIG_RECIPIENTS)


def any_config(current: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    if not any(
        current.has(p)
        for p in (Permission.CONFIG_CAMERAS, Permission.CONFIG_PPE, Permission.CONFIG_RECIPIENTS, Permission.ANNOTATIONS_CREATE)
    ):
        raise HTTPException(403, detail="Missing permission: config.cameras")
    return current


def cameras_or_ppe(current: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    if not (current.has(Permission.CONFIG_CAMERAS) or current.has(Permission.CONFIG_PPE)):
        raise HTTPException(403, detail="Missing permission: config.ppe")
    return current


def _commit_change(db: Session, request: Request, current: CurrentUser, action: str, details: str) -> int:
    version = bump_config_version(db, current.email)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, detail="That name is already in use here.")
    log_activity(db, request, action, current.id, current.email, details)
    return version


def _clean_name(value: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError("Name cannot be empty")
    return value


CleanName = Annotated[str, Field(min_length=1, max_length=100), AfterValidator(_clean_name)]
CleanArea = Annotated[str, Field(min_length=1, max_length=150), AfterValidator(_clean_name)]


# --- Overview -----------------------------------------------------------------------


def _camera_out(cam: Camera, health: dict[str, CameraHealth]) -> dict:
    h = health.get(cam.health_id)
    return {
        "id": cam.id,
        "production_house_id": cam.production_house_id,
        "area": cam.area,
        "stream_url": config_io.mask_stream_url(cam.stream_url),
        "enabled": cam.enabled,
        "scale_up": cam.scale_up,
        "notes": cam.notes,
        "ppe": [p.key for p in cam.ppe_items],
        "health": {"online": h.status, "last_checked": h.last_checked} if h else None,
        "updated_at": cam.updated_at,
    }


@router.get("/overview")
def overview(db: Session = Depends(get_db), _: CurrentUser = Depends(any_config)):
    health = {h.camera_id: h for h in db.scalars(select(CameraHealth)).all()}
    state = get_state(db)
    plants = db.scalars(select(Plant).order_by(Plant.name)).all()
    return {
        "config_version": state.config_version,
        "updated_at": state.updated_at,
        "updated_by": state.updated_by,
        "ppe_items": [
            {"id": p.id, "key": p.key, "display_name": p.display_name, "enabled": p.enabled}
            for p in db.scalars(select(PpeItem).order_by(PpeItem.sort_order, PpeItem.id)).all()
        ],
        "plants": [
            {
                "id": plant.id,
                "name": plant.name,
                "production_houses": [
                    {"id": ph.id, "name": ph.name, "cameras": [_camera_out(c, health) for c in ph.cameras]}
                    for ph in plant.production_houses
                ],
            }
            for plant in plants
        ],
    }


# --- Plants & production houses ------------------------------------------------------


class NameIn(BaseModel):
    name: CleanName


class HouseIn(NameIn):
    plant_id: int


@router.post("/plants", status_code=201)
def create_plant(body: NameIn, request: Request, db: Session = Depends(get_db), current: CurrentUser = Depends(cameras_perm)):
    plant = Plant(name=body.name)
    db.add(plant)
    _commit_change(db, request, current, "Add Plant", body.name)
    return {"id": plant.id, "name": plant.name}


@router.patch("/plants/{plant_id}")
def rename_plant(
    plant_id: int, body: NameIn, request: Request, db: Session = Depends(get_db), current: CurrentUser = Depends(cameras_perm)
):
    plant = db.get(Plant, plant_id) or _404("Plant")
    old = plant.name
    plant.name = body.name
    _commit_change(db, request, current, "Rename Plant", f"{old} -> {body.name}")
    return {"id": plant.id, "name": plant.name}


@router.delete("/plants/{plant_id}", status_code=204)
def delete_plant(plant_id: int, request: Request, db: Session = Depends(get_db), current: CurrentUser = Depends(cameras_perm)):
    plant = db.get(Plant, plant_id) or _404("Plant")
    if plant.production_houses:
        raise HTTPException(400, detail="Remove the plant's production houses first.")
    db.delete(plant)
    _commit_change(db, request, current, "Delete Plant", plant.name)


@router.post("/production-houses", status_code=201)
def create_house(body: HouseIn, request: Request, db: Session = Depends(get_db), current: CurrentUser = Depends(cameras_perm)):
    plant = db.get(Plant, body.plant_id) or _404("Plant")
    house = ProductionHouse(plant_id=plant.id, name=body.name)
    db.add(house)
    _commit_change(db, request, current, "Add Production House", f"{plant.name} / {body.name}")
    return {"id": house.id, "name": house.name, "plant_id": plant.id}


@router.patch("/production-houses/{house_id}")
def rename_house(
    house_id: int, body: NameIn, request: Request, db: Session = Depends(get_db), current: CurrentUser = Depends(cameras_perm)
):
    house = db.get(ProductionHouse, house_id) or _404("Production house")
    old = house.name
    house.name = body.name
    _commit_change(db, request, current, "Rename Production House", f"{old} -> {body.name}")
    return {"id": house.id, "name": house.name}


@router.delete("/production-houses/{house_id}", status_code=204)
def delete_house(house_id: int, request: Request, db: Session = Depends(get_db), current: CurrentUser = Depends(cameras_perm)):
    house = db.get(ProductionHouse, house_id) or _404("Production house")
    if house.cameras:
        raise HTTPException(400, detail="Remove or move the production house's cameras first.")
    db.query(AlertRecipient).filter(AlertRecipient.production_house_id == house.id).delete()
    db.delete(house)
    _commit_change(db, request, current, "Delete Production House", house.name)


def _404(what: str):
    raise HTTPException(404, detail=f"{what} not found.")


# --- Cameras ------------------------------------------------------------------------

STREAM_RE = re.compile(r"^(rtsp|rtsps|http|https)://", re.I)


class CameraIn(BaseModel):
    production_house_id: int
    area: CleanArea
    stream_url: str = Field(min_length=8, max_length=1000)
    enabled: bool = True
    scale_up: bool = False
    notes: str | None = Field(None, max_length=2000)
    ppe: list[str] = []

    @field_validator("stream_url")
    @classmethod
    def check_url(cls, v: str) -> str:
        v = v.strip()
        if not STREAM_RE.match(v):
            raise ValueError("Stream address must start with rtsp:// (or http(s)://)")
        return v


class CameraPatch(BaseModel):
    production_house_id: int | None = None
    area: str | None = Field(None, min_length=1, max_length=150)
    stream_url: str | None = Field(None, min_length=8, max_length=1000)
    enabled: bool | None = None
    scale_up: bool | None = None
    notes: str | None = Field(None, max_length=2000)
    ppe: list[str] | None = None

    @field_validator("stream_url")
    @classmethod
    def check_url(cls, v: str | None) -> str | None:
        if v is not None and not STREAM_RE.match(v.strip()):
            raise ValueError("Stream address must start with rtsp:// (or http(s)://)")
        return v.strip() if v else v


def _ppe_items(db: Session, keys: list[str]) -> list[PpeItem]:
    items = db.scalars(select(PpeItem).where(PpeItem.key.in_(keys))).all()
    missing = set(keys) - {i.key for i in items}
    if missing:
        raise HTTPException(400, detail=f"Unknown PPE: {', '.join(sorted(missing))}")
    return list(items)


def _label(cam: Camera) -> str:
    return f"{cam.production_house.name} / {cam.area}"


@router.post("/cameras", status_code=201)
def create_camera(body: CameraIn, request: Request, db: Session = Depends(get_db), current: CurrentUser = Depends(cameras_perm)):
    house = db.get(ProductionHouse, body.production_house_id) or _404("Production house")
    camera = Camera(
        production_house_id=house.id,
        area=body.area,
        stream_url=body.stream_url,
        enabled=body.enabled,
        scale_up=body.scale_up,
        notes=body.notes,
    )
    camera.ppe_items = _ppe_items(db, body.ppe)
    db.add(camera)
    _commit_change(db, request, current, "Add Camera", f"{house.name} / {body.area}")
    return _camera_out(camera, {})


@router.patch("/cameras/{camera_id}")
def update_camera(
    camera_id: int, body: CameraPatch, request: Request, db: Session = Depends(get_db), current: CurrentUser = Depends(cameras_or_ppe)
):
    camera = db.get(Camera, camera_id) or _404("Camera")
    fields = body.model_dump(exclude_unset=True)
    camera_fields = set(fields) - {"ppe"}
    if camera_fields and not current.has(Permission.CONFIG_CAMERAS):
        raise HTTPException(403, detail="Missing permission: config.cameras")

    changes = []
    if "production_house_id" in fields and fields["production_house_id"] != camera.production_house_id:
        db.get(ProductionHouse, fields["production_house_id"]) or _404("Production house")
        camera.production_house_id = fields["production_house_id"]
        changes.append("moved")
    if fields.get("area") and fields["area"].strip() != camera.area:
        changes.append(f"area {camera.area} -> {fields['area'].strip()}")
        camera.area = fields["area"].strip()
    if fields.get("stream_url"):
        new_url = config_io.unmask_stream_url(fields["stream_url"], camera.stream_url)
        if new_url != camera.stream_url:
            camera.stream_url = new_url
            changes.append("stream address")
    for flag in ("enabled", "scale_up"):
        if flag in fields and fields[flag] is not None and fields[flag] != getattr(camera, flag):
            setattr(camera, flag, fields[flag])
            changes.append(f"{flag}={fields[flag]}")
    if "notes" in fields:
        camera.notes = fields["notes"]
    if fields.get("ppe") is not None:
        before = sorted(p.key for p in camera.ppe_items)
        camera.ppe_items = _ppe_items(db, fields["ppe"])
        after = sorted(p.key for p in camera.ppe_items)
        if before != after:
            changes.append(f"PPE {','.join(before) or '-'} -> {','.join(after) or '-'}")
    db.flush()
    db.refresh(camera)
    _commit_change(db, request, current, "Update Camera", f"{_label(camera)}: {'; '.join(changes) or 'no changes'}")
    return _camera_out(camera, {})


@router.delete("/cameras/{camera_id}", status_code=204)
def delete_camera(camera_id: int, request: Request, db: Session = Depends(get_db), current: CurrentUser = Depends(cameras_perm)):
    camera = db.get(Camera, camera_id) or _404("Camera")
    label = _label(camera)
    db.delete(camera)
    _commit_change(db, request, current, "Delete Camera", label)


class BulkIn(BaseModel):
    camera_ids: list[int] = Field(min_length=1, max_length=2000)
    action: Literal["enable", "disable", "set_ppe", "add_ppe", "remove_ppe"]
    ppe: list[str] = []


@router.post("/cameras/bulk")
def bulk_update(body: BulkIn, request: Request, db: Session = Depends(get_db), current: CurrentUser = Depends(cameras_or_ppe)):
    needs = Permission.CONFIG_CAMERAS if body.action in ("enable", "disable") else None
    if needs and not current.has(needs):
        raise HTTPException(403, detail="Missing permission: config.cameras")
    cameras = db.scalars(select(Camera).where(Camera.id.in_(body.camera_ids))).all()
    items = _ppe_items(db, body.ppe) if body.ppe else []
    for cam in cameras:
        if body.action == "enable":
            cam.enabled = True
        elif body.action == "disable":
            cam.enabled = False
        elif body.action == "set_ppe":
            cam.ppe_items = list(items)
        elif body.action == "add_ppe":
            cam.ppe_items = cam.ppe_items + [i for i in items if i not in cam.ppe_items]
        elif body.action == "remove_ppe":
            cam.ppe_items = [p for p in cam.ppe_items if p not in items]
    detail = f"{body.action} on {len(cameras)} cameras" + (f" ({', '.join(body.ppe)})" if body.ppe else "")
    _commit_change(db, request, current, "Bulk Camera Update", detail)
    return {"updated": len(cameras)}


class StreamTestIn(BaseModel):
    stream_url: str = Field(min_length=8, max_length=1000)
    camera_id: int | None = None  # to restore a masked password


@router.post("/stream-test", response_class=Response)
def stream_test(body: StreamTestIn, db: Session = Depends(get_db), _: CurrentUser = Depends(cameras_perm)):
    """Grabs one frame so the person configuring a camera can see it works before saving."""
    current_url = None
    if body.camera_id:
        camera = db.get(Camera, body.camera_id)
        current_url = camera.stream_url if camera else None
    url = config_io.unmask_stream_url(body.stream_url.strip(), current_url)
    try:
        jpeg = vision.grab_frame(url)
    except vision.SnapshotError as e:
        raise HTTPException(502, detail=str(e))
    return Response(jpeg, media_type="image/jpeg", headers={"Cache-Control": "no-store"})


@router.get("/cameras/export")
def export_cameras(
    request: Request, include_disabled: bool = False, db: Session = Depends(get_db), current: CurrentUser = Depends(cameras_perm)
):
    data = config_io.export_camera_json(db, include_disabled=include_disabled)
    log_activity(db, request, "Export Cameras", current.id, current.email, "Camera list exported (contains stream credentials)")
    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    return Response(
        json.dumps(data, indent=4),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="camera_list_{stamp}.json"'},
    )


@router.post("/cameras/import")
async def import_cameras(
    request: Request,
    file: UploadFile = File(...),
    enable_new: bool = Form(True),
    update_existing: bool = Form(True),
    db: Session = Depends(get_db),
    current: CurrentUser = Depends(cameras_perm),
):
    try:
        data = json.loads((await file.read(5 * 1024 * 1024)).decode("utf-8"))
        if not isinstance(data, dict):
            raise ValueError
    except (ValueError, UnicodeDecodeError):
        raise HTTPException(400, detail="Upload a camera list JSON file (plant -> production house -> area).")
    result = config_io.import_camera_json(db, data, enable_new=enable_new, update_existing=update_existing)
    _commit_change(
        db,
        request,
        current,
        "Import Cameras",
        f"{file.filename}: {result.get('created', 0)} created, {result.get('updated', 0)} updated",
    )
    return result


# --- PPE items and the class registry ---------------------------------------------------


@router.get("/ppe")
def ppe_config(db: Session = Depends(get_db), _: CurrentUser = Depends(any_config)):
    usage = dict(
        db.execute(
            select(PpeItem.id, func.count(Camera.id))
            .join(Camera.ppe_items)
            .where(Camera.enabled.is_(True))
            .group_by(PpeItem.id)
        ).all()
    )
    state = get_state(db)
    active = db.get(ModelVersion, state.active_model_id) if state.active_model_id else None
    model_names = set(active.class_names or []) if active else set()
    return {
        "ppe_items": [
            {
                "id": p.id,
                "key": p.key,
                "display_name": p.display_name,
                "enabled": p.enabled,
                "sort_order": p.sort_order,
                "cameras": usage.get(p.id, 0),
            }
            for p in db.scalars(select(PpeItem).order_by(PpeItem.sort_order, PpeItem.id)).all()
        ],
        "classes": [
            {
                "class_id": c.class_id,
                "name": c.name,
                "ppe_item_id": c.ppe_item_id,
                "is_violation": c.is_violation,
                "threshold": c.threshold,
                "enabled": c.enabled,
                # False when the active model can't output this class yet (needs annotation + retraining)
                "in_active_model": c.name in model_names,
            }
            for c in db.scalars(select(ModelClass).order_by(ModelClass.class_id)).all()
        ],
        "active_model": {"id": active.id, "name": active.name} if active else None,
    }


KEY_RE = re.compile(r"^[a-z][a-z0-9_]{1,48}$")


class PpeItemIn(BaseModel):
    display_name: CleanName
    key: str | None = Field(None, max_length=50)
    # Also register "<Name>" and "No <Name>" classes so they can be annotated and trained
    create_classes: bool = True


class PpeItemPatch(BaseModel):
    display_name: str | None = Field(None, min_length=1, max_length=100)
    enabled: bool | None = None
    sort_order: int | None = None


@router.post("/ppe-items", status_code=201)
def create_ppe_item(body: PpeItemIn, request: Request, db: Session = Depends(get_db), current: CurrentUser = Depends(ppe_perm)):
    key = (body.key or re.sub(r"[^a-z0-9]+", "_", body.display_name.lower())).strip("_")
    if not KEY_RE.match(key):
        raise HTTPException(400, detail="Key must be lowercase letters, numbers and underscores.")
    if db.scalar(select(PpeItem).where(PpeItem.key == key)):
        raise HTTPException(409, detail=f"PPE '{key}' already exists.")
    next_order = (db.scalar(select(func.max(PpeItem.sort_order))) or 0) + 1
    item = PpeItem(key=key, display_name=body.display_name, sort_order=next_order, enabled=True)
    db.add(item)
    db.flush()
    created = []
    if body.create_classes:
        for name, violation in ((body.display_name, False), (f"No {body.display_name}", True)):
            if db.scalar(select(ModelClass).where(func.lower(ModelClass.name) == name.lower())):
                continue
            next_id = (db.scalar(select(func.max(ModelClass.class_id))) or -1) + 1
            db.add(ModelClass(class_id=next_id, name=name, ppe_item_id=item.id, is_violation=violation, threshold=0.6))
            db.flush()
            created.append(name)
    _commit_change(
        db, request, current, "Add PPE", f"{body.display_name} ({key})" + (f"; classes {', '.join(created)}" if created else "")
    )
    return {"id": item.id, "key": item.key, "classes_created": created}


@router.patch("/ppe-items/{item_id}")
def update_ppe_item(
    item_id: int, body: PpeItemPatch, request: Request, db: Session = Depends(get_db), current: CurrentUser = Depends(ppe_perm)
):
    item = db.get(PpeItem, item_id) or _404("PPE item")
    fields = body.model_dump(exclude_unset=True)
    for k, v in fields.items():
        if v is not None:
            setattr(item, k, v.strip() if isinstance(v, str) else v)
    _commit_change(db, request, current, "Update PPE", f"{item.key}: {fields}")
    return {"id": item.id}


class ClassPatch(BaseModel):
    threshold: float | None = Field(None, ge=0.05, le=0.99)
    enabled: bool | None = None


class ClassIn(BaseModel):
    name: CleanName
    ppe_item_id: int | None = None
    is_violation: bool = False
    threshold: float = Field(0.6, ge=0.05, le=0.99)


@router.patch("/classes/{class_id}")
def update_class(
    class_id: int, body: ClassPatch, request: Request, db: Session = Depends(get_db), current: CurrentUser = Depends(ppe_perm)
):
    cls = db.get(ModelClass, class_id) or _404("Class")
    changes = []
    if body.threshold is not None and abs(body.threshold - cls.threshold) > 1e-9:
        changes.append(f"threshold {cls.threshold:.2f} -> {body.threshold:.2f}")
        cls.threshold = round(body.threshold, 3)
    if body.enabled is not None and body.enabled != cls.enabled:
        changes.append("enabled" if body.enabled else "disabled")
        cls.enabled = body.enabled
    _commit_change(db, request, current, "Update Class", f"{cls.name}: {'; '.join(changes) or 'no changes'}")
    return {"class_id": cls.class_id, "threshold": cls.threshold, "enabled": cls.enabled}


@router.post("/classes", status_code=201)
def create_class(body: ClassIn, request: Request, db: Session = Depends(get_db), current: CurrentUser = Depends(ppe_perm)):
    if db.scalar(select(ModelClass).where(func.lower(ModelClass.name) == body.name.lower())):
        raise HTTPException(409, detail=f"Class '{body.name}' already exists.")
    if body.ppe_item_id is not None:
        db.get(PpeItem, body.ppe_item_id) or _404("PPE item")
    # YOLO needs contiguous ids, so new classes always go on the end
    next_id = (db.scalar(select(func.max(ModelClass.class_id))) or -1) + 1
    cls = ModelClass(
        class_id=next_id,
        name=body.name,
        ppe_item_id=body.ppe_item_id,
        is_violation=body.is_violation,
        threshold=body.threshold,
    )
    db.add(cls)
    _commit_change(db, request, current, "Add Class", f"{body.name} (id {next_id})")
    return {"class_id": next_id, "name": body.name}


# --- Alert recipients -----------------------------------------------------------------


class RecipientIn(BaseModel):
    email: EmailStr
    kind: Literal["to", "cc", "bcc"] = "to"
    designation: str | None = Field(None, max_length=150)


class RecipientsIn(BaseModel):
    recipients: list[RecipientIn] = Field(max_length=100)


def _recipient_out(r: AlertRecipient) -> dict:
    return {"id": r.id, "email": r.email, "kind": r.kind, "designation": r.designation}


@router.get("/recipients")
def list_recipients(db: Session = Depends(get_db), _: CurrentUser = Depends(recipients_perm)):
    rows = db.scalars(select(AlertRecipient).order_by(AlertRecipient.kind.desc(), AlertRecipient.email)).all()
    by_house: dict[int, list[dict]] = {}
    health = []
    for r in rows:
        if r.channel == "camera_health":
            health.append(_recipient_out(r))
        elif r.production_house_id:
            by_house.setdefault(r.production_house_id, []).append(_recipient_out(r))
    houses = db.execute(
        select(ProductionHouse, Plant.name).join(Plant, Plant.id == ProductionHouse.plant_id).order_by(Plant.name, ProductionHouse.name)
    ).all()
    camera_counts = dict(
        db.execute(select(Camera.production_house_id, func.count()).where(Camera.enabled.is_(True)).group_by(Camera.production_house_id)).all()
    )
    return {
        "production_houses": [
            {
                "id": ph.id,
                "name": ph.name,
                "plant": plant_name,
                "cameras": camera_counts.get(ph.id, 0),
                "recipients": by_house.get(ph.id, []),
            }
            for ph, plant_name in houses
        ],
        "camera_health": health,
    }


def _replace_recipients(db: Session, channel: str, house_id: int | None, recipients: list[RecipientIn]) -> int:
    db.query(AlertRecipient).filter(
        AlertRecipient.channel == channel,
        AlertRecipient.production_house_id.is_(None) if house_id is None else AlertRecipient.production_house_id == house_id,
    ).delete(synchronize_session=False)
    seen = set()
    for r in recipients:
        email = r.email.lower()
        if email in seen:
            continue
        seen.add(email)
        db.add(
            AlertRecipient(
                channel=channel,
                production_house_id=house_id,
                email=email,
                kind=r.kind,
                designation=(r.designation or "").strip() or None,
            )
        )
    return len(seen)


@router.put("/recipients/production-houses/{house_id}")
def set_house_recipients(
    house_id: int, body: RecipientsIn, request: Request, db: Session = Depends(get_db), current: CurrentUser = Depends(recipients_perm)
):
    house = db.get(ProductionHouse, house_id) or _404("Production house")
    if body.recipients and not any(r.kind == "to" for r in body.recipients):
        raise HTTPException(400, detail="Add at least one 'To' recipient, or remove them all.")
    n = _replace_recipients(db, "violation", house.id, body.recipients)
    db.commit()
    log_activity(db, request, "Update Recipients", current.id, current.email, f"{house.name}: {n} recipients")
    return {"count": n}


@router.put("/recipients/camera-health")
def set_health_recipients(
    body: RecipientsIn, request: Request, db: Session = Depends(get_db), current: CurrentUser = Depends(recipients_perm)
):
    n = _replace_recipients(db, "camera_health", None, body.recipients)
    db.commit()
    log_activity(db, request, "Update Recipients", current.id, current.email, f"Camera health digest: {n} recipients")
    return {"count": n}
