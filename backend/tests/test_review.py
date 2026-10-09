from datetime import date, time

from app.db.models import PpeEvent, Sample
from tests.conftest import jpeg_bytes


def make_event(db, storage, with_frame=True):
    if with_frame:
        storage.put_bytes("raw/2026-10/evt1.jpg", jpeg_bytes(1920, 1080), "image/jpeg")
    e = PpeEvent(
        class1="No Helmet",
        production_house="PP-25",
        area="NITRATOR",
        date1=date(2026, 10, 8),
        time1=time(9, 0),
        image_url="local://october/evt1.jpg",
        violation=True,
        raw_image_key="raw/2026-10/evt1.jpg" if with_frame else None,
        frame_width=1920,
        frame_height=1080,
        detections=[
            # No Helmet at 0.91 (threshold 0.78): pre-filled
            {"class_id": 6, "name": "No Helmet", "conf": 0.91, "box": [960, 100, 1056, 208], "used": True},
            # Gloves at 0.40 (threshold 0.70): offered as a suggestion only
            {"class_id": 0, "name": "Gloves", "conf": 0.40, "box": [100, 500, 160, 560], "used": False},
        ]
        if with_frame
        else None,
    )
    db.add(e)
    db.commit()
    return e


def test_detail_splits_prefill_and_suggestions(as_user, db, storage):
    event = make_event(db, storage)
    client = as_user("violations.review")
    data = client.get(f"/api/events/{event.id}").json()
    assert data["has_clean_frame"] is True
    assert [lb["class_id"] for lb in data["labels"]] == [6]
    lb = data["labels"][0]
    assert abs(lb["cx"] - 0.525) < 1e-6 and abs(lb["w"] - 0.05) < 1e-6
    assert [s["class_id"] for s in data["suggestions"]] == [0]

    raw = client.get(f"/api/events/{event.id}/image", params={"variant": "raw"})
    assert raw.status_code == 200 and raw.headers["content-type"] == "image/jpeg"
    # Annotated image recorded as local:// but never written -> clean 404
    assert client.get(f"/api/events/{event.id}/image").status_code == 404


def test_false_positive_with_relabel_produces_yolo_files(as_user, db, storage):
    event = make_event(db, storage)
    reviewer = as_user("violations.review")
    queue = reviewer.get("/api/events").json()
    assert queue["total"] == 1

    # The model said "No Helmet" but the worker is wearing one: relabel the box as Helmet (2)
    labels = [{"class_id": 2, "cx": 0.525, "cy": 0.1426, "w": 0.05, "h": 0.1, "origin": "human"}]
    r = reviewer.post(f"/api/events/{event.id}/review", json={"verdict": "false_positive", "labels": labels, "approve": True})
    assert r.status_code == 200, r.text
    # approve was requested but the reviewer can't approve: goes to QA instead
    assert r.json()["sample"]["status"] == "submitted"

    db.refresh(event)
    assert event.violation is False and event.review_status == "false_positive"
    assert reviewer.get("/api/events").json()["total"] == 0
    assert not storage.exists(f"training-pool/labels/{r.json()['sample']['id']}.txt")

    # An approver accepts it into the pool
    approver = as_user("annotations.approve", email="qa.lead@solargroup.com")
    sample_id = r.json()["sample"]["id"]
    assert approver.post(f"/api/samples/{sample_id}/approve").status_code == 200
    assert storage.get_bytes(f"training-pool/labels/{sample_id}.txt").decode() == "2 0.525000 0.142600 0.050000 0.100000\n"
    assert storage.exists(f"training-pool/images/{sample_id}.jpg")


def test_reviewer_who_can_approve_goes_straight_to_pool(as_user, db, storage):
    event = make_event(db, storage)
    client = as_user("violations.review", "annotations.approve")
    r = client.post(f"/api/events/{event.id}/review", json={"verdict": "confirmed", "labels": [], "approve": True})
    sample_id = r.json()["sample"]["id"]
    assert r.json()["sample"]["status"] == "approved"
    # Every box deleted -> background image with an empty label file
    assert storage.get_bytes(f"training-pool/labels/{sample_id}.txt") == b""

    # Reviewing again updates the same sample instead of creating another
    client.post(f"/api/events/{event.id}/review", json={"verdict": "confirmed", "labels": [], "approve": True})
    assert db.query(Sample).filter(Sample.ppes_id == event.id).count() == 1


def test_verdict_only_and_legacy_events(as_user, db, storage):
    event = make_event(db, storage, with_frame=False)
    client = as_user("violations.review")
    r = client.post(f"/api/events/{event.id}/review", json={"verdict": "false_positive"})
    assert r.status_code == 200 and r.json()["sample"] is None
    r = client.post(f"/api/events/{event.id}/review", json={"verdict": "confirmed", "labels": []})
    assert r.status_code == 400 and "clean frame" in r.json()["detail"]
    # The failed request changed nothing: the earlier false-positive verdict stands
    db.refresh(event)
    assert event.violation is False and event.review_status == "false_positive"
