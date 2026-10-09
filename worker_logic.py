"""
Pure logic shared by inference.py and trainer.py.

Nothing here imports cv2, torch, ultralytics, boto3 or psycopg2, so the rules that
decide what gets detected, alerted and trained on can be unit-tested anywhere
(see worker_tests/).
"""
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import quote_plus

FRAME_W, FRAME_H = 1920, 1080

# Legacy spellings the older models and camera JSONs used
_CLASS_ALIASES = {
    "glove": "gloves",
    "shoe": "shoes",
    "goggle": "goggles",
    "no_glove": "no_gloves",
    "no_shoe": "no_shoes",
    "no_goggle": "no_goggles",
}

TRAINER_PAUSE_PREFIX = "Retraining run #"


def normalize_class_name(name):
    """'No Helmet' / 'no_helmet' / 'NO HELMET' -> 'no_helmet' (with legacy aliases folded)."""
    s = str(name).strip().lower().replace("-", "_").replace(" ", "_")
    while "__" in s:
        s = s.replace("__", "_")
    return _CLASS_ALIASES.get(s, s)


# ==============================================================================
# CLASS REGISTRY (model_classes + ppe_items)
# ==============================================================================
@dataclass(frozen=True)
class ClassMeta:
    class_id: int
    name: str
    is_violation: bool
    threshold: float
    ppe_key: str  # base PPE item ('helmet', ...); '' when the class maps to no PPE item
    ppe_display: str


class ClassRegistry:
    """Immutable lookup from model output names to registry rows. Swapped atomically on reload."""

    def __init__(self, metas, ppe_display=None):
        self.metas = tuple(sorted(metas, key=lambda m: m.class_id))
        self._by_norm = {normalize_class_name(m.name): m for m in self.metas}
        # ppe key -> display name, for HUD chips (includes PPE items with no classes)
        self.ppe_display = dict(ppe_display or {})
        for m in self.metas:
            if m.ppe_key and m.ppe_key not in self.ppe_display:
                self.ppe_display[m.ppe_key] = m.ppe_display or m.ppe_key.capitalize()

    @classmethod
    def from_rows(cls, class_rows, ppe_rows=()):
        """class_rows: (class_id, name, is_violation, threshold, ppe_key, ppe_display)
        ppe_rows: (key, display_name) for enabled PPE items."""
        metas = [
            ClassMeta(
                class_id=int(cid),
                name=str(name),
                is_violation=bool(is_violation),
                threshold=float(threshold),
                ppe_key=ppe_key or "",
                ppe_display=ppe_display or (ppe_key or "").capitalize(),
            )
            for cid, name, is_violation, threshold, ppe_key, ppe_display in class_rows
        ]
        return cls(metas, {k: d for k, d in ppe_rows})

    def lookup(self, model_name):
        return self._by_norm.get(normalize_class_name(model_name))

    def display_for(self, ppe_key):
        return self.ppe_display.get(ppe_key, ppe_key.capitalize())

    def __len__(self):
        return len(self.metas)


# ==============================================================================
# CAMERA SPECS (cameras + camera_ppe)
# ==============================================================================
@dataclass(frozen=True)
class CameraSpec:
    id: int
    plant: str
    production_house: str
    area: str
    stream_url: str
    scale_up: bool
    required_items: frozenset

    @property
    def health_id(self):
        """camera_health.camera_id, same composition the old inference.py used."""
        return f"{self.plant}_{self.production_house}_{self.area}"

    @property
    def ip_address(self):
        """Host part of the RTSP URL; stored in ppes.camera_unit like before."""
        after_at = self.stream_url.split("@", 1)[1] if "@" in self.stream_url else self.stream_url
        if "://" in after_at:
            after_at = after_at.split("://", 1)[1]
        host = after_at.split("/", 1)[0]
        return host.split(":", 1)[0] if ":" in host else (host or "0.0.0.0")

    @property
    def label(self):
        return f"{self.production_house} | {self.area}"


def build_camera_specs(rows, all_ppe_keys):
    """rows: (camera_id, plant, production_house, area, stream_url, scale_up, ppe_key|None),
    one row per camera x required PPE item (LEFT JOIN, so None when a camera has none).
    A camera with no required PPE monitors every enabled item, like the legacy default."""
    grouped = {}
    for cam_id, plant, ph, area, url, scale_up, ppe_key in rows:
        entry = grouped.setdefault(int(cam_id), {"base": (plant, ph, area, url, bool(scale_up)), "ppe": set()})
        if ppe_key:
            entry["ppe"].add(ppe_key)

    all_keys = frozenset(all_ppe_keys)
    specs = {}
    for cam_id, entry in grouped.items():
        plant, ph, area, url, scale_up = entry["base"]
        required = frozenset(entry["ppe"] & all_keys) if entry["ppe"] & all_keys else all_keys
        specs[cam_id] = CameraSpec(cam_id, plant, ph, area, url, scale_up, required)
    return specs


def diff_camera_specs(running, desired):
    """Returns (start, stop, restart) id lists to move from `running` to `desired`."""
    start = sorted(set(desired) - set(running))
    stop = sorted(set(running) - set(desired))
    restart = sorted(cid for cid in set(running) & set(desired) if running[cid] != desired[cid])
    return start, stop, restart


# ==============================================================================
# DETECTIONS
# ==============================================================================
def classify_detections(raw, registry, required_items):
    """raw: iterable of (model_class_name, conf, [x1, y1, x2, y2]) from the model.

    Every box whose class is in the registry is returned (for the review UI);
    `used` marks the ones that count for alerting: confidence >= the class threshold
    AND the class's PPE item is required in this area. Unknown classes are dropped."""
    out = []
    for model_name, conf, box in raw:
        meta = registry.lookup(model_name)
        if meta is None:
            continue
        b = [int(round(float(v))) for v in box]
        conf = float(conf)
        out.append({
            "box": b,
            "center": ((b[0] + b[2]) / 2, (b[1] + b[3]) / 2),
            "class_id": meta.class_id,
            "name": meta.name,
            "class_name": normalize_class_name(meta.name),
            "display_name": meta.name,
            "base_item": meta.ppe_key,
            "is_violation": meta.is_violation,
            "conf": conf,
            "used": conf >= meta.threshold and meta.ppe_key in required_items,
        })
    return out


def detections_payload(detections):
    """JSON stored in ppes.detections (box in 1920x1080 pixels)."""
    return [
        {
            "class_id": d["class_id"],
            "name": d["name"],
            "conf": round(d["conf"], 3),
            "box": [int(v) for v in d["box"]],
            "used": bool(d["used"]),
        }
        for d in detections
    ]


def summarize_event(used):
    """Strings and counts for the single ppes row, as the old inference.py wrote them."""
    violations = [d for d in used if d["is_violation"]]
    compliances = [d for d in used if not d["is_violation"]]
    unique_v = sorted({d["display_name"] for d in violations})
    unique_c = sorted({d["display_name"] for d in compliances})
    return {
        "violations_str": ", ".join(unique_v),
        "compliance_str": ", ".join(unique_c) if unique_c else "None",
        "violation_count": len(violations),
        "compliance_count": len(compliances),
    }


# ==============================================================================
# STORAGE KEYS & URLS
# ==============================================================================
def event_image_id(now, production_house, area):
    return f"{now.strftime('%Y-%m-%d')}{now.strftime('%H%M%S')}_{production_house}_{area}"


def event_image_keys(now, im_id):
    """(annotated key, clean raw-frame key). The annotated key keeps the legacy month layout."""
    return f"{now.strftime('%B').lower()}/{im_id}.jpg", f"raw/{now.strftime('%Y-%m')}/{im_id}.jpg"


def public_image_url(public_base, bucket, key):
    """The URL format cooldown.py and the legacy dashboard parse; do not change."""
    return f"{public_base.rstrip('/')}/{bucket}/{quote_plus(key)}"


def local_image_url(key):
    return f"local://{key}"


def trainer_owns_pause(pause_reason):
    return bool(pause_reason) and str(pause_reason).startswith(TRAINER_PAUSE_PREFIX)


# ==============================================================================
# TRAINING
# ==============================================================================
DEFAULT_TRAIN_PARAMS = {
    "epochs": 50,
    "imgsz": 640,
    "batch": 16,
    "patience": 20,
    "lr0": None,
    "device": "0",
    "workers": 4,
}


def parse_train_params(params):
    """training_runs.params JSON -> ultralytics kwargs with defaults and sane bounds."""
    p = dict(DEFAULT_TRAIN_PARAMS)
    p.update({k: v for k, v in (params or {}).items() if v is not None or k == "lr0"})

    def clamp_int(key, lo, hi):
        p[key] = max(lo, min(hi, int(p[key])))

    clamp_int("epochs", 1, 1000)
    clamp_int("imgsz", 32, 2560)
    p["imgsz"] -= p["imgsz"] % 32  # YOLO needs a stride multiple
    clamp_int("batch", -1, 512)  # -1 = ultralytics auto-batch
    clamp_int("patience", 0, 1000)
    clamp_int("workers", 0, 32)
    p["lr0"] = float(p["lr0"]) if p["lr0"] not in (None, "") else None
    p["device"] = str(p["device"])
    return p


def _yaml_quote(value):
    return "'" + str(value).replace("'", "''") + "'"


def build_data_yaml(dataset_dir, class_names):
    """Ultralytics data.yaml pointing at a local dataset mirror."""
    lines = [
        f"path: {_yaml_quote(dataset_dir)}",
        "train: images/train",
        "val: images/val",
        f"nc: {len(class_names)}",
        "names:",
    ]
    lines += [f"  {i}: {_yaml_quote(n)}" for i, n in enumerate(class_names)]
    return "\n".join(lines) + "\n"


# Keys ultralytics puts in trainer.metrics for detection models
_METRIC_KEYS = {
    "precision": "metrics/precision(B)",
    "recall": "metrics/recall(B)",
    "map50": "metrics/mAP50(B)",
    "map50_95": "metrics/mAP50-95(B)",
}


def box_metrics(trainer_metrics):
    out = {}
    for ours, theirs in _METRIC_KEYS.items():
        value = (trainer_metrics or {}).get(theirs)
        out[ours] = round(float(value), 4) if value is not None else None
    return out


def build_progress(epoch, epochs, trainer_metrics, history):
    """training_runs.progress. `epoch` is 1-based; history is appended to in place."""
    metrics = box_metrics(trainer_metrics)
    history.append({"epoch": epoch, **metrics})
    return {"epoch": epoch, "epochs": epochs, "metrics": metrics, "history": list(history)}


def summarize_class_results(names, class_indices, class_results, overall):
    """Metrics JSON for a validation run.

    names: {class_index: name}; class_indices: classes that had validation instances;
    class_results: matching (precision, recall, map50, map50_95) tuples;
    overall: (precision, recall, map50, map50_95)."""
    p, r, m50, m = overall
    per_class = {}
    for idx, (cp, cr, c50, c) in zip(class_indices, class_results):
        per_class[str(names.get(int(idx), idx))] = {
            "map50_95": round(float(c), 4),
            "map50": round(float(c50), 4),
            "precision": round(float(cp), 4),
            "recall": round(float(cr), 4),
        }
    return {
        "map50": round(float(m50), 4),
        "map50_95": round(float(m), 4),
        "precision": round(float(p), 4),
        "recall": round(float(r), 4),
        "per_class": per_class,
    }


def same_class_names(a, b):
    return [normalize_class_name(x) for x in (a or [])] == [normalize_class_name(x) for x in (b or [])]


class RollingLog:
    """Keeps the tail of a console stream. tqdm redraws with '\\r'; only the final state
    of each line is kept so the stored log stays readable."""

    def __init__(self, limit=8000):
        self.limit = limit
        self._lines = []
        self._current = ""

    def write(self, text):
        parts = str(text).split("\n")
        for i, part in enumerate(parts):
            if "\r" in part:
                # A terminal would redraw the line; keep only the last non-empty redraw
                redraws = [s for s in part.split("\r") if s]
                self._current = redraws[-1] if redraws else ""
            else:
                self._current += part
            if i < len(parts) - 1:
                self._lines.append(self._current)
                self._current = ""
        self._trim()

    def _trim(self):
        total = sum(len(line) + 1 for line in self._lines)
        while self._lines and total > self.limit:
            total -= len(self._lines.pop(0)) + 1

    def text(self):
        body = "\n".join(self._lines + ([self._current] if self._current else []))
        return body[-self.limit:]


def format_timestamp(now=None):
    return (now or datetime.now()).strftime("%Y-%m-%d %H:%M:%S")
