"""Training samples: image intake, YOLO label files and the approved training pool."""
import hashlib
import io
import uuid
from dataclasses import dataclass

from PIL import Image, ImageOps, UnidentifiedImageError
from sqlalchemy.orm import Session

from app.core.security import utcnow
from app.db.models import ModelClass, Sample, SampleLabel
from app.services.storage import Storage, copy_into_main

POOL_PREFIX = "training-pool"
ALLOWED_FORMATS = {"JPEG", "PNG", "BMP", "WEBP", "TIFF"}


class InvalidImage(ValueError):
    pass


@dataclass
class StoredImage:
    key: str
    width: int
    height: int
    sha1: str


def store_image(storage: Storage, data: bytes, prefix: str = "samples") -> StoredImage:
    """Validates an image, normalises it to an upright RGB JPEG and stores it."""
    try:
        img = Image.open(io.BytesIO(data))
        img.load()
    except (UnidentifiedImageError, OSError) as e:
        raise InvalidImage("Not a readable image file.") from e
    if img.format not in ALLOWED_FORMATS:
        raise InvalidImage(f"Unsupported image format: {img.format}.")

    orientation = img.getexif().get(0x0112, 1)
    if img.format == "JPEG" and img.mode == "RGB" and orientation == 1:
        out = data  # already an upright RGB JPEG: keep the original bytes
    else:
        upright = ImageOps.exif_transpose(img)
        buf = io.BytesIO()
        upright.convert("RGB").save(buf, format="JPEG", quality=92)
        out = buf.getvalue()
        img = upright

    sha1 = hashlib.sha1(out).hexdigest()
    key = f"{prefix}/{utcnow():%Y-%m}/{uuid.uuid4().hex}.jpg"
    storage.put_bytes(key, out, "image/jpeg")
    return StoredImage(key=key, width=img.width, height=img.height, sha1=sha1)


def clamp_box(cx: float, cy: float, w: float, h: float) -> tuple[float, float, float, float] | None:
    """Clips a normalised box to the image; drops boxes that end up degenerate."""
    x1, y1 = max(0.0, cx - w / 2), max(0.0, cy - h / 2)
    x2, y2 = min(1.0, cx + w / 2), min(1.0, cy + h / 2)
    if x2 - x1 < 1e-4 or y2 - y1 < 1e-4:
        return None
    return (x1 + x2) / 2, (y1 + y2) / 2, x2 - x1, y2 - y1


def pixel_box_to_yolo(box: list[float], width: int, height: int) -> tuple[float, float, float, float] | None:
    x1, y1, x2, y2 = box
    return clamp_box(((x1 + x2) / 2) / width, ((y1 + y2) / 2) / height, (x2 - x1) / width, (y2 - y1) / height)


def yolo_txt(labels: list[SampleLabel]) -> str:
    """'<class_id> <cx> <cy> <w> <h>' per line, 6 decimals. Empty string = background image."""
    lines = [f"{lb.class_id} {lb.cx:.6f} {lb.cy:.6f} {lb.w:.6f} {lb.h:.6f}" for lb in labels]
    return "\n".join(lines) + ("\n" if lines else "")


def replace_labels(db: Session, sample: Sample, labels: list[dict]) -> None:
    valid_ids = {cid for (cid,) in db.query(ModelClass.class_id).all()}
    new = []
    for lb in labels:
        if lb["class_id"] not in valid_ids:
            raise ValueError(f"Unknown class id {lb['class_id']}.")
        box = clamp_box(lb["cx"], lb["cy"], lb["w"], lb["h"])
        if box is None:
            continue
        cx, cy, w, h = box
        new.append(
            SampleLabel(
                class_id=lb["class_id"], cx=cx, cy=cy, w=w, h=h, origin=lb.get("origin") or "human", conf=lb.get("conf")
            )
        )
    sample.labels.clear()
    sample.labels.extend(new)


def pool_keys(sample_id: int) -> tuple[str, str]:
    return f"{POOL_PREFIX}/images/{sample_id}.jpg", f"{POOL_PREFIX}/labels/{sample_id}.txt"


def write_to_pool(storage: Storage, sample: Sample) -> None:
    """The approved pool is always a ready-to-train YOLO folder: images/ + labels/."""
    image_key, label_key = pool_keys(sample.id)
    copy_into_main(sample.image_key, image_key)
    storage.put_bytes(label_key, yolo_txt(sample.labels).encode("utf-8"), "text/plain")


def remove_from_pool(storage: Storage, sample_id: int) -> None:
    for key in pool_keys(sample_id):
        storage.delete(key)
