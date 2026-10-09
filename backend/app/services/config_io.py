"""Import/export between the database config and the legacy formats.

camera_list_*.json:  {plant: {production_house: {area: {"streamLink": ..., "ppeList": ["no_helmet", ...]}}}}
seed/recipients.json: {"violation": {ph: {"to": [...], "cc": [...]}},
                       "camera_health": {"to": [...], "cc": [...], "bcc": [...]},
                       "designations": {email: title}}
"""
from collections import Counter
from urllib.parse import urlsplit, urlunsplit

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import AlertRecipient, Camera, Plant, PpeItem, ProductionHouse
from app.services.classes import normalize

MASK = "••••"


# --- Stream URLs ------------------------------------------------------------------


def mask_stream_url(url: str) -> str:
    """rtsp://user:secret@host/path -> rtsp://user:••••@host/path"""
    parts = urlsplit(url)
    if parts.password is None:
        return url
    host = parts.netloc.rsplit("@", 1)[1]
    return urlunsplit(parts._replace(netloc=f"{parts.username}:{MASK}@{host}"))


def unmask_stream_url(new_url: str, current_url: str | None) -> str:
    """The UI only ever sees masked URLs. When one comes back unchanged, restore the real password."""
    if MASK not in new_url or not current_url:
        return new_url
    password = urlsplit(current_url).password or ""
    return new_url.replace(MASK, password, 1)


# --- PPE keys ---------------------------------------------------------------------


def ppe_key_from_legacy(value: str) -> str:
    """'no_glove' / 'Gloves' / 'no helmet' -> 'gloves' / 'gloves' / 'helmet'"""
    s = normalize(value)
    if s.startswith("no "):
        s = s[3:]
    return s.replace(" ", "_")


def legacy_ppe_name(key: str) -> str:
    # The legacy files spelled gloves as no_glove; everything else is no_<key>
    return "no_glove" if key == "gloves" else f"no_{key}"


# --- Cameras ----------------------------------------------------------------------


def _get_or_create_plant(db: Session, name: str) -> Plant:
    plant = db.scalar(select(Plant).where(Plant.name == name))
    if plant is None:
        plant = Plant(name=name)
        db.add(plant)
        db.flush()
    return plant


def _get_or_create_house(db: Session, plant: Plant, name: str) -> ProductionHouse:
    house = db.scalar(select(ProductionHouse).where(ProductionHouse.plant_id == plant.id, ProductionHouse.name == name))
    if house is None:
        house = ProductionHouse(plant_id=plant.id, name=name)
        db.add(house)
        db.flush()
    return house


def import_camera_json(db: Session, data: dict, enable_new: bool = True, update_existing: bool = True) -> dict:
    """Merges a legacy camera list into the database. Does not commit."""
    items = {i.key: i for i in db.scalars(select(PpeItem)).all()}
    stats = Counter()
    unknown_ppe: set[str] = set()
    for plant_name, houses in data.items():
        if not isinstance(houses, dict):
            continue
        plant = _get_or_create_plant(db, plant_name)
        for house_name, areas in houses.items():
            if not isinstance(areas, dict):
                continue
            house = _get_or_create_house(db, plant, house_name)
            for area, spec in areas.items():
                if not isinstance(spec, dict) or not spec.get("streamLink"):
                    stats["skipped"] += 1
                    continue
                ppe: list[PpeItem] = []
                for raw in spec.get("ppeList") or []:
                    key = ppe_key_from_legacy(raw)
                    if key not in items:
                        unknown_ppe.add(raw)
                    elif items[key] not in ppe:  # some legacy areas list an item twice
                        ppe.append(items[key])
                camera = db.scalar(
                    select(Camera).where(Camera.production_house_id == house.id, Camera.area == area)
                )
                if camera is None:
                    camera = Camera(
                        production_house_id=house.id,
                        area=area,
                        stream_url=spec["streamLink"],
                        enabled=enable_new,
                        scale_up=bool(spec.get("non_uniform_scale", False)),
                    )
                    camera.ppe_items = ppe
                    db.add(camera)
                    stats["created"] += 1
                elif update_existing:
                    changed = camera.stream_url != spec["streamLink"] or {p.id for p in camera.ppe_items} != {
                        p.id for p in ppe
                    }
                    camera.stream_url = spec["streamLink"]
                    camera.ppe_items = ppe
                    stats["updated" if changed else "unchanged"] += 1
                else:
                    stats["unchanged"] += 1
    db.flush()
    return {k: stats[k] for k in ("created", "updated", "unchanged", "skipped")} | {"unknown_ppe": sorted(unknown_ppe)}


def export_camera_json(db: Session, include_disabled: bool = False) -> dict:
    out: dict = {}
    for plant in db.scalars(select(Plant).order_by(Plant.name)).all():
        for house in plant.production_houses:
            for cam in house.cameras:
                if not cam.enabled and not include_disabled:
                    continue
                spec = {"streamLink": cam.stream_url, "ppeList": [legacy_ppe_name(p.key) for p in cam.ppe_items]}
                if cam.scale_up:
                    spec["non_uniform_scale"] = True
                out.setdefault(plant.name, {}).setdefault(house.name, {})[cam.area] = spec
    return out


# --- Recipients -------------------------------------------------------------------


def import_recipients(db: Session, seed: dict, plant_name: str | None = None) -> dict:
    """Replaces the recipients of every production house named in the seed. Houses that
    don't exist yet are created (under plant_name, or the only plant) so no address is lost;
    they are reported so someone can reconcile names like 'DF-01' vs 'DF01'."""
    plants = db.scalars(select(Plant)).all()
    if plant_name:
        plant = _get_or_create_plant(db, plant_name)
    elif len(plants) == 1:
        plant = plants[0]
    else:
        raise ValueError("Pass the plant name: the seed does not say which plant its production houses belong to.")

    designations = {k.lower(): v for k, v in (seed.get("designations") or {}).items()}
    created_houses, houses_without_cameras = [], []
    count = 0
    for house_name, lists in (seed.get("violation") or {}).items():
        house = db.scalar(select(ProductionHouse).where(ProductionHouse.plant_id == plant.id, ProductionHouse.name == house_name))
        if house is None:
            house = _get_or_create_house(db, plant, house_name)
            created_houses.append(house_name)
        if not house.cameras:
            houses_without_cameras.append(house_name)
        db.query(AlertRecipient).filter(
            AlertRecipient.channel == "violation", AlertRecipient.production_house_id == house.id
        ).delete()
        seen = set()
        for kind in ("to", "cc", "bcc"):
            for email in lists.get(kind) or []:
                email = email.strip().lower()
                if not email or email in seen:
                    continue
                seen.add(email)
                db.add(
                    AlertRecipient(
                        channel="violation",
                        production_house_id=house.id,
                        email=email,
                        kind=kind,
                        designation=designations.get(email),
                    )
                )
                count += 1

    health = seed.get("camera_health") or {}
    if health:
        db.query(AlertRecipient).filter(AlertRecipient.channel == "camera_health").delete()
        seen = set()
        for kind in ("to", "cc", "bcc"):
            for email in health.get(kind) or []:
                email = email.strip().lower()
                if email and email not in seen:
                    seen.add(email)
                    db.add(AlertRecipient(channel="camera_health", email=email, kind=kind))
                    count += 1

    all_houses = {h.name for h in db.scalars(select(ProductionHouse).where(ProductionHouse.plant_id == plant.id)).all()}
    with_recipients = set((seed.get("violation") or {}).keys())
    db.flush()
    return {
        "recipients": count,
        "created_houses": sorted(created_houses),
        "houses_without_cameras": sorted(houses_without_cameras),
        "houses_without_recipients": sorted(all_houses - with_recipients),
    }
