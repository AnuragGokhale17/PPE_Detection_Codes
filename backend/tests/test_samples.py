import io

from PIL import Image

from app.db.models import Sample
from tests.conftest import jpeg_bytes


def png_bytes(w=80, h=40):
    buf = io.BytesIO()
    Image.new("RGBA", (w, h), (10, 200, 10, 255)).save(buf, format="PNG")
    return buf.getvalue()


def upload(client, *files):
    return client.post(
        "/api/samples/upload",
        files=[("files", (name, data, "application/octet-stream")) for name, data in files],
        data={"production_house": "PP-25", "area": "NITRATOR"},
    )


def test_upload_normalises_and_dedupes(as_user, db, storage):
    client = as_user("annotations.create")
    r = upload(client, ("a.jpg", jpeg_bytes()), ("b.png", png_bytes()), ("c.txt", b"not an image"), ("a-again.jpg", jpeg_bytes()))
    assert r.status_code == 201, r.text
    body = r.json()
    assert len(body["created"]) == 2
    reasons = {s["file"]: s["reason"] for s in body["skipped"]}
    assert "readable image" in reasons["c.txt"]
    assert "Already uploaded" in reasons["a-again.jpg"]

    png_sample = db.get(Sample, body["created"][1])
    assert (png_sample.width, png_sample.height) == (80, 40)
    assert png_sample.image_key.endswith(".jpg")
    stored = Image.open(io.BytesIO(storage.get_bytes(png_sample.image_key)))
    assert stored.format == "JPEG" and stored.mode == "RGB"


def test_label_submit_approve_reject_cycle(as_user, db, storage):
    annotator = as_user("annotations.create")
    sid = upload(annotator, ("a.jpg", jpeg_bytes())).json()["created"][0]

    bad = annotator.put(f"/api/samples/{sid}/labels", json={"labels": [{"class_id": 99, "cx": 0.5, "cy": 0.5, "w": 0.1, "h": 0.1}]})
    assert bad.status_code == 400
    r = annotator.put(
        f"/api/samples/{sid}/labels",
        json={
            "labels": [
                {"class_id": 6, "cx": 0.5, "cy": 0.5, "w": 0.2, "h": 0.2},
                # Hangs off the right edge: clipped to the image
                {"class_id": 4, "cx": 0.95, "cy": 0.5, "w": 0.2, "h": 0.2},
            ]
        },
    )
    assert r.status_code == 200
    clipped = r.json()["labels"][1]
    assert abs(clipped["cx"] - 0.925) < 1e-9 and abs(clipped["w"] - 0.15) < 1e-9

    assert annotator.post(f"/api/samples/{sid}/submit").json()["status"] == "submitted"
    assert annotator.post(f"/api/samples/{sid}/approve").status_code == 403

    approver = as_user("annotations.approve", email="qa.lead@solargroup.com")
    approver.post(f"/api/samples/{sid}/approve")
    txt = storage.get_bytes(f"training-pool/labels/{sid}.txt").decode().splitlines()
    assert txt == ["6 0.500000 0.500000 0.200000 0.200000", "4 0.925000 0.500000 0.150000 0.200000"]

    # Annotators can't touch approved work; approvers can, and the pool follows
    assert annotator.put(f"/api/samples/{sid}/labels", json={"labels": []}).status_code == 403
    approver.put(f"/api/samples/{sid}/labels", json={"labels": [{"class_id": 2, "cx": 0.5, "cy": 0.5, "w": 0.1, "h": 0.1}]})
    assert storage.get_bytes(f"training-pool/labels/{sid}.txt").decode().startswith("2 ")

    approver.post(f"/api/samples/{sid}/reject", json={"reason": "Box too loose"})
    assert not storage.exists(f"training-pool/labels/{sid}.txt")
    # Rejected work goes back to the annotator, who can fix and resubmit
    assert annotator.put(f"/api/samples/{sid}/labels", json={"labels": []}).json()["status"] == "draft"


def test_stats_and_listing(as_user, storage):
    annotator = as_user("annotations.create", "annotations.approve")
    ids = upload(annotator, ("a.jpg", jpeg_bytes(color=(1, 2, 3))), ("b.jpg", jpeg_bytes(color=(9, 9, 9)))).json()["created"]
    annotator.put(f"/api/samples/{ids[0]}/labels", json={"labels": [{"class_id": 6, "cx": 0.5, "cy": 0.5, "w": 0.1, "h": 0.1}] * 2})
    annotator.post(f"/api/samples/{ids[0]}/approve")
    annotator.post(f"/api/samples/{ids[1]}/approve")  # no boxes: a background image

    stats = annotator.get("/api/samples/stats").json()
    assert stats["status_counts"]["approved"] == 2
    assert stats["background_images"] == 1
    no_helmet = next(c for c in stats["classes"] if c["name"] == "No Helmet")
    assert (no_helmet["approved_instances"], no_helmet["approved_images"]) == (2, 1)

    listing = annotator.get("/api/samples", params={"class_id": 6}).json()
    assert [s["id"] for s in listing["items"]] == [ids[0]]
    # Queue navigation runs newest -> oldest within the same status
    detail = annotator.get(f"/api/samples/{ids[1]}").json()
    assert (detail["next_id"], detail["prev_id"]) == (ids[0], None)


def test_delete_rules_and_suggestions_unavailable(as_user, db, storage):
    owner = as_user("annotations.create")
    other = as_user("annotations.create", email="someone.else@solargroup.com")
    sid = upload(owner, ("a.jpg", jpeg_bytes())).json()["created"][0]
    key = db.get(Sample, sid).image_key

    assert other.delete(f"/api/samples/{sid}").status_code == 403
    # Ultralytics isn't installed in the test environment
    r = owner.post(f"/api/samples/{sid}/suggest")
    assert r.status_code == 501 and "requirements-ml.txt" in r.json()["detail"]

    assert owner.delete(f"/api/samples/{sid}").status_code == 204
    assert not storage.exists(key)

    assert as_user().get("/api/samples").status_code == 403
