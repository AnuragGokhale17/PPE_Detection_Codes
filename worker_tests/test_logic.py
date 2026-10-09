from datetime import datetime

import pytest

from worker_logic import (
    ClassRegistry,
    CameraSpec,
    RollingLog,
    build_camera_specs,
    build_data_yaml,
    build_progress,
    classify_detections,
    detections_payload,
    diff_camera_specs,
    event_image_id,
    event_image_keys,
    local_image_url,
    normalize_class_name,
    parse_train_params,
    public_image_url,
    same_class_names,
    summarize_class_results,
    summarize_event,
    trainer_owns_pause,
)

# Seed rows as migration 0003 inserts them: (class_id, name, is_violation, threshold, ppe key, display)
CLASS_ROWS = [
    (0, "Gloves", False, 0.70, "gloves", "Gloves"),
    (1, "Goggles", False, 0.60, "goggles", "Goggles"),
    (2, "Helmet", False, 0.70, "helmet", "Helmet"),
    (3, "Mask", False, 0.60, "mask", "Mask"),
    (4, "No Gloves", True, 0.80, "gloves", "Gloves"),
    (5, "No Goggles", True, 0.60, "goggles", "Goggles"),
    (6, "No Helmet", True, 0.78, "helmet", "Helmet"),
    (7, "No Mask", True, 0.58, "mask", "Mask"),
    (8, "No Shoes", True, 0.80, "shoes", "Shoes"),
    (9, "No Suit", True, 0.65, "suit", "Suit"),
    (10, "Shoes", False, 0.70, "shoes", "Shoes"),
    (11, "Suit", False, 0.65, "suit", "Suit"),
]
PPE_ROWS = [("helmet", "Helmet"), ("gloves", "Hand gloves"), ("goggles", "Goggles"),
            ("mask", "Mask"), ("suit", "Suit"), ("shoes", "Shoes")]


@pytest.fixture
def registry():
    return ClassRegistry.from_rows(CLASS_ROWS, PPE_ROWS)


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("No Helmet", "no_helmet"),
        ("no_helmet", "no_helmet"),
        ("  NO  HELMET ", "no_helmet"),
        ("no_glove", "no_gloves"),
        ("Glove", "gloves"),
        ("no-shoe", "no_shoes"),
        ("goggle", "goggles"),
    ],
)
def test_normalize_class_name(raw, expected):
    assert normalize_class_name(raw) == expected


def test_registry_maps_model_names_and_ppe_display(registry):
    assert registry.lookup("no_glove").class_id == 4
    assert registry.lookup("NO HELMET").threshold == 0.78
    assert registry.lookup("Harness") is None
    # Display names come from ppe_items, not the class names
    assert registry.display_for("gloves") == "Hand gloves"
    assert registry.display_for("unknown") == "Unknown"
    assert len(registry) == 12


def test_build_camera_specs_groups_ppe_and_defaults_to_all():
    rows = [
        (1, "CHAKDOH", "PP-25", "MIXING", "rtsp://u:p@10.0.0.5:554/s", False, "helmet"),
        (1, "CHAKDOH", "PP-25", "MIXING", "rtsp://u:p@10.0.0.5:554/s", False, "gloves"),
        (2, "CHAKDOH", "PB-1", "SEIVING", "rtsp://10.0.0.6/s", True, None),
        # A disabled PPE item comes back as None from the LEFT JOIN
        (3, "CHAKDOH", "PB-1", "STORE", "rtsp://u:p@10.0.0.7/s", False, "harness"),
    ]
    specs = build_camera_specs(rows, ["helmet", "gloves", "shoes"])
    assert specs[1].required_items == frozenset({"helmet", "gloves"})
    assert specs[2].required_items == frozenset({"helmet", "gloves", "shoes"})
    assert specs[2].scale_up is True
    # Only unknown/disabled items configured -> monitor everything
    assert specs[3].required_items == frozenset({"helmet", "gloves", "shoes"})
    assert specs[1].health_id == "CHAKDOH_PP-25_MIXING"
    assert specs[1].ip_address == "10.0.0.5"
    assert specs[2].ip_address == "10.0.0.6"


def _spec(cid, url="rtsp://a", items=("helmet",), area="A"):
    return CameraSpec(cid, "P", "PH", area, url, False, frozenset(items))


def test_diff_camera_specs():
    running = {1: _spec(1), 2: _spec(2), 3: _spec(3)}
    desired = {1: _spec(1), 2: _spec(2, url="rtsp://new"), 4: _spec(4)}
    start, stop, restart = diff_camera_specs(running, desired)
    assert (start, stop, restart) == ([4], [3], [2])
    assert diff_camera_specs(desired, desired) == ([], [], [])


def test_classify_detections_marks_used_by_threshold_and_area(registry):
    raw = [
        ("No Helmet", 0.90, [100.4, 50, 200, 150]),  # above 0.78, helmet required -> used
        ("No Helmet", 0.50, [300, 50, 400, 150]),  # below threshold -> kept for review, not used
        ("No Suit", 0.99, [500, 50, 600, 300]),  # suit not required here -> not used
        ("Harness", 0.99, [0, 0, 10, 10]),  # not in the registry -> dropped
    ]
    dets = classify_detections(raw, registry, frozenset({"helmet", "gloves"}))
    assert [d["used"] for d in dets] == [True, False, False]
    assert dets[0]["box"] == [100, 50, 200, 150]
    assert dets[0]["class_id"] == 6 and dets[0]["base_item"] == "helmet" and dets[0]["is_violation"]

    payload = detections_payload(dets)
    assert payload[0] == {"class_id": 6, "name": "No Helmet", "conf": 0.9, "box": [100, 50, 200, 150], "used": True}
    assert set(payload[1]) == {"class_id", "name", "conf", "box", "used"}


def test_summarize_event(registry):
    dets = classify_detections(
        [("No Helmet", 0.9, [0, 0, 1, 1]), ("No Helmet", 0.9, [5, 5, 6, 6]), ("Gloves", 0.9, [0, 0, 1, 1])],
        registry,
        frozenset({"helmet", "gloves"}),
    )
    s = summarize_event([d for d in dets if d["used"]])
    assert s == {"violations_str": "No Helmet", "compliance_str": "Gloves", "violation_count": 2, "compliance_count": 1}
    assert summarize_event([])["compliance_str"] == "None"


def test_event_keys_and_urls():
    now = datetime(2026, 10, 9, 14, 5, 7)
    im_id = event_image_id(now, "PP-25", "MIXING AREA")
    assert im_id == "2026-10-09140507_PP-25_MIXING AREA"
    annotated, raw = event_image_keys(now, im_id)
    assert annotated == "october/2026-10-09140507_PP-25_MIXING AREA.jpg"
    assert raw == "raw/2026-10/2026-10-09140507_PP-25_MIXING AREA.jpg"
    # Same format as the legacy inference.py (quote_plus: '/' -> %2F, ' ' -> '+')
    assert public_image_url("https://ppes-siil.solargroup.com:9000/", "mybucket", annotated) == (
        "https://ppes-siil.solargroup.com:9000/mybucket/october%2F2026-10-09140507_PP-25_MIXING+AREA.jpg"
    )
    assert local_image_url(raw) == "local://raw/2026-10/2026-10-09140507_PP-25_MIXING AREA.jpg"


def test_trainer_owns_pause():
    assert trainer_owns_pause("Retraining run #12")
    assert not trainer_owns_pause("Maintenance by admin")
    assert not trainer_owns_pause(None)


def test_parse_train_params_defaults_and_bounds():
    p = parse_train_params({"epochs": "30", "imgsz": 650, "batch": 8, "lr0": None})
    assert p["epochs"] == 30 and p["imgsz"] == 640 and p["batch"] == 8
    assert p["lr0"] is None and p["device"] == "0" and p["workers"] == 4 and p["patience"] == 20
    p = parse_train_params({"epochs": 0, "lr0": "0.002", "device": 1})
    assert p["epochs"] == 1 and p["lr0"] == 0.002 and p["device"] == "1"
    assert parse_train_params(None)["epochs"] == 50


def test_build_data_yaml_round_trips():
    yaml = pytest.importorskip("yaml")
    text = build_data_yaml("/srv/runs/3/dataset", ["Gloves", "No Gloves", "Worker's vest"])
    data = yaml.safe_load(text)
    assert data["path"] == "/srv/runs/3/dataset"
    assert data["train"] == "images/train" and data["val"] == "images/val"
    assert data["nc"] == 3
    assert data["names"] == {0: "Gloves", 1: "No Gloves", 2: "Worker's vest"}


def test_build_progress_accumulates_history():
    history = []
    m = {"metrics/precision(B)": 0.81234, "metrics/recall(B)": 0.7, "metrics/mAP50(B)": 0.66, "metrics/mAP50-95(B)": 0.41}
    build_progress(1, 50, m, history)
    p = build_progress(2, 50, {}, history)
    assert p["epoch"] == 2 and p["epochs"] == 50
    assert p["metrics"] == {"precision": None, "recall": None, "map50": None, "map50_95": None}
    assert p["history"][0] == {"epoch": 1, "precision": 0.8123, "recall": 0.7, "map50": 0.66, "map50_95": 0.41}
    assert len(p["history"]) == 2


def test_summarize_class_results():
    out = summarize_class_results(
        {0: "Gloves", 6: "No Helmet"},
        [0, 6],
        [(0.9, 0.8, 0.85, 0.6), (0.7, 0.5, 0.55, 0.3)],
        (0.8, 0.65, 0.7, 0.45),
    )
    assert out["map50_95"] == 0.45 and out["precision"] == 0.8
    assert out["per_class"]["No Helmet"] == {"map50_95": 0.3, "map50": 0.55, "precision": 0.7, "recall": 0.5}
    assert set(out["per_class"]) == {"Gloves", "No Helmet"}


def test_same_class_names():
    assert same_class_names(["No Helmet", "Gloves"], ["no_helmet", "gloves"])
    assert not same_class_names(["Gloves"], ["Gloves", "Harness"])


def test_rolling_log_collapses_carriage_returns_and_trims():
    buf = RollingLog(limit=60)
    buf.write("Epoch 1/3\n")
    buf.write("  10%|#   |\r  50%|#####|\r 100%|##########|\n")
    buf.write("partial")
    buf.write(" line")
    assert buf.text().splitlines() == ["Epoch 1/3", " 100%|##########|", "partial line"]
    for i in range(20):
        buf.write(f"line {i}\n")
    assert len(buf.text()) <= 60
    assert buf.text().endswith("line 19")
