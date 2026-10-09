"""Camera snapshots (OpenCV) and model-assisted labelling (Ultralytics, optional)."""
import io
import logging
import os
import threading
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import ModelClass, ModelVersion
from app.services.classes import normalize
from app.services.runtime import get_state

log = logging.getLogger(__name__)

# Must be set before OpenCV opens its first stream. TCP avoids smeared frames on the plant
# network; the timeouts stop a dead camera from hanging the request.
os.environ.setdefault(
    "OPENCV_FFMPEG_CAPTURE_OPTIONS", "rtsp_transport;tcp|timeout;5000000|stimeout;5000000|buffer_size;1024000"
)

FRAME_SIZE = (1920, 1080)  # inference.py works on 1080p frames; snapshots match


class SnapshotError(Exception):
    pass


class PrelabelUnavailable(Exception):
    pass


def grab_frame(stream_url: str) -> bytes:
    """Reads one current frame from an RTSP stream and returns it as a 1080p JPEG."""
    import cv2

    timeout = get_settings().snapshot_timeout_seconds
    result: dict = {}

    def worker():
        cap = cv2.VideoCapture(stream_url, cv2.CAP_FFMPEG)
        try:
            if not cap.isOpened():
                result["error"] = "Could not open the stream. Check the address and credentials."
                return
            cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            for _ in range(3):  # drain buffered frames to land on a current one
                cap.grab()
            ok, frame = cap.read()
            if not ok or frame is None:
                result["error"] = "The stream opened but returned no frame."
                return
            frame = cv2.resize(frame, FRAME_SIZE)
            ok, jpg = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 92])
            if not ok:
                result["error"] = "Could not encode the frame."
                return
            result["jpeg"] = jpg.tobytes()
        except Exception as e:  # noqa: BLE001 - surfaced to the user as a message
            result["error"] = f"Stream error: {e}"
        finally:
            cap.release()

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    thread.join(timeout)
    if thread.is_alive():
        raise SnapshotError(f"The camera did not respond within {timeout} seconds.")
    if "error" in result:
        raise SnapshotError(result["error"])
    return result["jpeg"]


# --- Model-assisted labelling -----------------------------------------------------

_model_lock = threading.Lock()
_model_cache: dict[int, object] = {}


def _resolve_weights(path: str) -> Path:
    p = Path(path)
    return p if p.is_absolute() else get_settings().models_root / p


def _active_model(db: Session):
    try:
        from ultralytics import YOLO
    except ImportError as e:
        raise PrelabelUnavailable(
            "Model suggestions need the ML extras on the API server (pip install -r requirements-ml.txt)."
        ) from e

    state = get_state(db)
    mv = db.get(ModelVersion, state.active_model_id) if state.active_model_id else None
    if mv is None:
        raise PrelabelUnavailable("No active model is configured.")
    weights = _resolve_weights(mv.weights_path)
    if not weights.is_file():
        raise PrelabelUnavailable(f"Model weights not found on this server: {mv.weights_path}")
    with _model_lock:
        if mv.id not in _model_cache:
            _model_cache.clear()
            log.info("Loading %s for model suggestions", weights)
            _model_cache[mv.id] = YOLO(str(weights))
        return _model_cache[mv.id]


def suggest_labels(db: Session, image_bytes: bytes) -> list[dict]:
    """Runs the active model on one image and returns normalised boxes mapped to the class registry."""
    from PIL import Image

    settings = get_settings()
    model = _active_model(db)
    registry = {normalize(c.name): c.class_id for c in db.scalars(select(ModelClass)).all()}
    image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    with _model_lock:
        results = model.predict(image, conf=settings.prelabel_conf, device=settings.prelabel_device, verbose=False)

    labels = []
    for result in results:
        names = result.names
        for xywhn, cls, conf in zip(result.boxes.xywhn.tolist(), result.boxes.cls.tolist(), result.boxes.conf.tolist()):
            class_id = registry.get(normalize(names[int(cls)]))
            if class_id is None:
                continue
            cx, cy, w, h = xywhn
            labels.append(
                {"class_id": class_id, "cx": cx, "cy": cy, "w": w, "h": h, "origin": "model", "conf": round(conf, 3)}
            )
    return labels
