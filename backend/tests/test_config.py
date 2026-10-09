import io
import json

from app.db.models import Camera, RuntimeState
from app.services import config_io

LEGACY = {
    "CHAKDOH": {
        "PP-25": {
            "NITRATOR_ROOM": {
                "streamLink": "rtsp://iiot:Secret%40123@10.0.34.23:554/profile3/media.smp",
                "ppeList": ["no_glove", "no_shoes", "no_goggles", "no_mask"],
            },
            # Duplicate entries exist in the real camera_list_v4.json
            "CRYSTALLIZER": {"streamLink": "rtsp://iiot:Secret%40123@10.0.34.24:554/p", "ppeList": ["no_helmet", "no_helmet"]},
        },
        "BULK": {"LOADING_BAY": {"streamLink": "rtsp://10.0.1.5/stream", "ppeList": []}},
    }
}


def _import(client):
    files = {"file": ("cams.json", io.BytesIO(json.dumps(LEGACY).encode()), "application/json")}
    return client.post("/api/config/cameras/import", files=files)


def _cameras(overview):
    return {c["area"]: c for p in overview["plants"] for ph in p["production_houses"] for c in ph["cameras"]}


def test_import_masks_credentials_and_bumps_version(as_user, db):
    admin = as_user(role="admin", email="cfg.admin@solargroup.com")
    r = _import(admin)
    assert r.status_code == 200, r.text
    assert r.json()["created"] == 3

    overview = admin.get("/api/config/overview").json()
    assert overview["config_version"] == 2
    cams = _cameras(overview)
    assert cams["NITRATOR_ROOM"]["stream_url"] == "rtsp://iiot:••••@10.0.34.23:554/profile3/media.smp"
    assert "Secret" not in json.dumps(overview)
    assert cams["NITRATOR_ROOM"]["ppe"] == ["gloves", "goggles", "mask", "shoes"]
    assert cams["LOADING_BAY"]["stream_url"] == "rtsp://10.0.1.5/stream"

    # Re-importing the same file changes nothing
    again = _import(admin).json()
    assert again["created"] == 0 and again["unchanged"] == 3


def test_masked_url_round_trip_keeps_password(as_user, db):
    admin = as_user(role="admin", email="cfg.admin@solargroup.com")
    _import(admin)
    cam = _cameras(admin.get("/api/config/overview").json())["NITRATOR_ROOM"]
    r = admin.patch(
        f"/api/config/cameras/{cam['id']}",
        json={"stream_url": cam["stream_url"].replace("profile3", "profile2"), "scale_up": True},
    )
    assert r.status_code == 200, r.text
    stored = db.get(Camera, cam["id"])
    db.refresh(stored)
    assert stored.stream_url == "rtsp://iiot:Secret%40123@10.0.34.23:554/profile2/media.smp"
    assert stored.scale_up is True


def test_ppe_permission_cannot_change_cameras(as_user):
    admin = as_user(role="admin", email="cfg.admin@solargroup.com")
    _import(admin)
    cam = _cameras(admin.get("/api/config/overview").json())["CRYSTALLIZER"]

    ppe_editor = as_user("config.ppe")
    assert ppe_editor.patch(f"/api/config/cameras/{cam['id']}", json={"ppe": ["helmet", "suit"]}).status_code == 200
    assert ppe_editor.patch(f"/api/config/cameras/{cam['id']}", json={"enabled": False}).status_code == 403
    assert ppe_editor.post("/api/config/plants", json={"name": "NEW"}).status_code == 403

    viewer = as_user()
    assert viewer.get("/api/config/overview").status_code == 403


def test_camera_crud_and_bulk(as_user, db):
    admin = as_user(role="admin", email="cfg.admin@solargroup.com")
    plant = admin.post("/api/config/plants", json={"name": "  NAGPUR "}).json()
    assert plant["name"] == "NAGPUR"
    house = admin.post("/api/config/production-houses", json={"plant_id": plant["id"], "name": "PB-9"}).json()
    assert admin.post("/api/config/production-houses", json={"plant_id": plant["id"], "name": "PB-9"}).status_code == 409

    bad = admin.post(
        "/api/config/cameras",
        json={"production_house_id": house["id"], "area": "A", "stream_url": "ftp://x/y", "ppe": []},
    )
    assert bad.status_code == 422
    ids = []
    for area in ("A", "B"):
        r = admin.post(
            "/api/config/cameras",
            json={"production_house_id": house["id"], "area": area, "stream_url": "rtsp://u:p@1.2.3.4/s", "ppe": ["helmet"]},
        )
        assert r.status_code == 201, r.text
        ids.append(r.json()["id"])

    r = admin.post("/api/config/cameras/bulk", json={"camera_ids": ids, "action": "add_ppe", "ppe": ["mask"]})
    assert r.json()["updated"] == 2
    admin.post("/api/config/cameras/bulk", json={"camera_ids": ids, "action": "disable"})
    cams = _cameras(admin.get("/api/config/overview").json())
    assert cams["A"]["ppe"] == ["helmet", "mask"] and cams["A"]["enabled"] is False

    assert admin.delete(f"/api/config/production-houses/{house['id']}").status_code == 400
    for cid in ids:
        assert admin.delete(f"/api/config/cameras/{cid}").status_code == 204
    assert admin.delete(f"/api/config/production-houses/{house['id']}").status_code == 204

    logs = admin.get("/api/audit-logs", params={"q": "Camera"}).json()
    assert logs["total"] >= 4
    assert db.get(RuntimeState, 1).config_version > 5


def test_new_ppe_item_registers_classes_at_the_end(as_user):
    admin = as_user(role="admin", email="cfg.admin@solargroup.com")
    r = admin.post("/api/config/ppe-items", json={"display_name": "Harness"})
    assert r.status_code == 201, r.text
    assert r.json()["key"] == "harness"
    assert r.json()["classes_created"] == ["Harness", "No Harness"]

    cfg = admin.get("/api/config/ppe").json()
    new = [c for c in cfg["classes"] if c["class_id"] >= 12]
    assert [(c["class_id"], c["name"], c["is_violation"], c["in_active_model"]) for c in new] == [
        (12, "Harness", False, False),
        (13, "No Harness", True, False),
    ]
    assert admin.post("/api/config/ppe-items", json={"display_name": "Harness"}).status_code == 409


def test_threshold_update_is_bounded_and_audited(as_user):
    editor = as_user("config.ppe")
    assert editor.patch("/api/config/classes/6", json={"threshold": 1.5}).status_code == 422
    r = editor.patch("/api/config/classes/6", json={"threshold": 0.72})
    assert r.json()["threshold"] == 0.72
    classes = {c["name"]: c for c in editor.get("/api/config/ppe").json()["classes"]}
    assert classes["No Helmet"]["threshold"] == 0.72


def test_recipients(as_user, db):
    admin = as_user(role="admin", email="cfg.admin@solargroup.com")
    _import(admin)
    houses = admin.get("/api/config/recipients").json()["production_houses"]
    pp25 = next(h for h in houses if h["name"] == "PP-25")

    r = admin.put(
        f"/api/config/recipients/production-houses/{pp25['id']}",
        json={"recipients": [{"email": "cc.only@solargroup.com", "kind": "cc"}]},
    )
    assert r.status_code == 400  # needs a To

    r = admin.put(
        f"/api/config/recipients/production-houses/{pp25['id']}",
        json={
            "recipients": [
                {"email": "Lead.Person@solargroup.com", "kind": "to", "designation": "Nitration lead"},
                {"email": "lead.person@solargroup.com", "kind": "cc"},
                {"email": "boss@solargroup.com", "kind": "cc"},
            ]
        },
    )
    assert r.json()["count"] == 2
    admin.put("/api/config/recipients/camera-health", json={"recipients": [{"email": "it@solargroup.com"}]})
    data = admin.get("/api/config/recipients").json()
    pp25 = next(h for h in data["production_houses"] if h["name"] == "PP-25")
    assert {(r["email"], r["kind"]) for r in pp25["recipients"]} == {
        ("lead.person@solargroup.com", "to"),
        ("boss@solargroup.com", "cc"),
    }
    assert data["camera_health"][0]["email"] == "it@solargroup.com"

    assert as_user("config.cameras").get("/api/config/recipients").status_code == 403


def test_recipient_seed_import_reports_name_mismatches(db):
    config_io.import_camera_json(db, LEGACY)
    seed = {
        "violation": {"PP-25": {"to": ["a.b@solargroup.com"], "cc": [""]}, "PP-2S": {"to": ["x.y@solargroup.com"]}},
        "camera_health": {"to": ["it@solargroup.com"], "bcc": ["audit@solargroup.com"]},
        "designations": {"a.b@solargroup.com": "Lead"},
    }
    result = config_io.import_recipients(db, seed)
    db.commit()
    assert result["recipients"] == 4
    assert result["created_houses"] == ["PP-2S"]
    assert result["houses_without_recipients"] == ["BULK"]


def test_export_round_trip(db):
    config_io.import_camera_json(db, LEGACY)
    db.commit()
    exported = config_io.export_camera_json(db)
    assert exported["CHAKDOH"]["PP-25"]["NITRATOR_ROOM"]["ppeList"] == ["no_glove", "no_goggles", "no_mask", "no_shoes"]
    assert exported["CHAKDOH"]["PP-25"]["NITRATOR_ROOM"]["streamLink"].startswith("rtsp://iiot:Secret%40123@")


def test_mask_helpers():
    url = "rtsp://iiot:Toshiba%40123@10.0.34.23:554/x"
    masked = config_io.mask_stream_url(url)
    assert masked == "rtsp://iiot:••••@10.0.34.23:554/x"
    assert config_io.unmask_stream_url(masked, url) == url
    assert config_io.unmask_stream_url("rtsp://new:pw@h/x", url) == "rtsp://new:pw@h/x"
    assert config_io.ppe_key_from_legacy("no_glove") == "gloves"
    assert config_io.ppe_key_from_legacy("No Helmet") == "helmet"
