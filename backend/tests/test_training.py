from app.db.models import DatasetVersion, ModelVersion, RuntimeState, Sample, SampleLabel, TrainingRun, WorkerHeartbeat
from app.core.security import utcnow
from app.services import datasets as dataset_svc
from tests.conftest import jpeg_bytes


def approved_samples(db, storage, per_area=5, areas=("A", "B")):
    ids = []
    for area in areas:
        for i in range(per_area):
            key = f"samples/test/{area}{i}.jpg"
            storage.put_bytes(key, jpeg_bytes(), "image/jpeg")
            s = Sample(image_key=key, width=64, height=36, source="upload", status="approved", production_house="PP", area=area)
            s.labels.append(SampleLabel(class_id=6, cx=0.5, cy=0.5, w=0.1, h=0.1))
            db.add(s)
            db.flush()
            ids.append(s.id)
    db.commit()
    return ids


def build(admin, name, sync=True):
    r = admin.post("/api/datasets", json={"name": name, "val_ratio": 0.2})
    assert r.status_code == 202, r.text
    return r.json()["id"]


def test_dataset_build_is_stratified_and_splits_are_stable(as_user, db, storage, monkeypatch):
    # Build synchronously in the test instead of in a thread
    monkeypatch.setattr(dataset_svc, "start_build", dataset_svc.build)
    approved_samples(db, storage)
    admin = as_user(role="admin", email="ml.admin@solargroup.com")

    ds_id = build(admin, "v1")
    ds = db.get(DatasetVersion, ds_id)
    db.refresh(ds)
    assert ds.status == "ready", ds.error
    assert (ds.sample_count, ds.train_count, ds.val_count) == (10, 8, 2)
    # One validation image per area
    val_areas = sorted(s.area for s in db.query(Sample).filter(Sample.split == "val"))
    assert val_areas == ["A", "B"]
    assert ds.class_counts["train"]["No Helmet"] == 8
    yaml = storage.get_bytes("datasets/v1/data.yaml").decode()
    assert "nc: 12" in yaml and "6: 'No Helmet'" in yaml
    some_val = db.query(Sample).filter(Sample.split == "val").first()
    assert storage.exists(f"datasets/v1/images/val/{some_val.id}.jpg")
    assert storage.get_bytes(f"datasets/v1/labels/val/{some_val.id}.txt").startswith(b"6 ")

    before = {s.id: s.split for s in db.query(Sample)}
    approved_samples(db, storage, per_area=5, areas=("A",))
    build(admin, "v2")
    db.expire_all()
    after = {s.id: s.split for s in db.query(Sample)}
    assert all(after[i] == split for i, split in before.items())  # nobody moved between train and val
    assert db.query(DatasetVersion).filter_by(name="v2").one().sample_count == 15

    assert admin.post("/api/datasets", json={"name": "v2"}).status_code == 409
    assert admin.post("/api/datasets", json={"name": "bad name!"}).status_code == 400


def test_empty_pool_fails_cleanly(as_user, db, monkeypatch):
    monkeypatch.setattr(dataset_svc, "start_build", dataset_svc.build)
    admin = as_user(role="admin", email="ml.admin@solargroup.com")
    ds_id = build(admin, "empty")
    ds = db.get(DatasetVersion, ds_id)
    db.refresh(ds)
    assert ds.status == "failed" and "empty" in ds.error


def test_runs_queue_cancel_and_validation(as_user, db, storage, monkeypatch):
    monkeypatch.setattr(dataset_svc, "start_build", dataset_svc.build)
    approved_samples(db, storage)
    admin = as_user(role="admin", email="ml.admin@solargroup.com")
    ds_id = build(admin, "v1")

    r = admin.post("/api/training/runs", json={"dataset_version_id": ds_id, "epochs": 5, "imgsz": 640, "batch": 4})
    assert r.status_code == 201, r.text
    run = r.json()
    assert run["status"] == "queued" and run["base_model"]["id"] == 1
    assert run["params"]["epochs"] == 5 and run["params"]["device"] == "0"
    assert admin.post("/api/training/runs", json={"dataset_version_id": ds_id, "imgsz": 650}).status_code == 422

    assert admin.post(f"/api/training/runs/{run['id']}/cancel").json()["status"] == "cancelled"
    assert admin.post(f"/api/training/runs/{run['id']}/cancel").status_code == 400

    # Adding a class makes the dataset stale for training
    admin.post("/api/config/ppe-items", json={"display_name": "Harness"})
    r = admin.post("/api/training/runs", json={"dataset_version_id": ds_id})
    assert r.status_code == 400 and "Classes changed" in r.json()["detail"]

    assert as_user("annotations.approve").get("/api/training/runs").status_code == 403


def test_activate_model_and_pause_controls(as_user, db):
    admin = as_user(role="admin", email="ml.admin@solargroup.com")
    names = db.get(ModelVersion, 1).class_names
    db.add(ModelVersion(id=2, name="run-7", weights_path="model/versions/2/best.pt", class_names=names, source="training"))
    db.add(ModelVersion(id=3, name="odd", weights_path="x.pt", class_names=["Cat", "Dog"], source="training"))
    db.commit()

    r = admin.post("/api/models/2/activate")
    assert r.status_code == 200 and r.json()["is_active"] is True
    state = db.get(RuntimeState, 1)
    db.refresh(state)
    assert state.active_model_id == 2
    assert [m["is_active"] for m in admin.get("/api/models").json()] == [False, True, False]
    assert admin.post("/api/models/3/activate").status_code == 400
    # Roll back
    admin.post("/api/models/1/activate")
    db.refresh(state)
    assert state.active_model_id == 1

    r = admin.post("/api/system/inference/pause", json={"reason": "Retraining run #9 (manual)"})
    db.refresh(state)
    assert state.inference_paused and state.pause_reason.startswith("Manual:")

    db.add(WorkerHeartbeat(name="inference", last_seen=utcnow(), info={"state": "paused", "cameras_running": 0}))
    db.add(TrainingRun(dataset_version_id=_dataset(db), base_model_id=1, params={}, status="running"))
    db.commit()
    status = as_user().get("/api/system/status").json()
    assert status["inference_paused"] is True
    assert status["workers"]["inference"]["online"] is True
    assert status["training"]["running_run_id"] is not None

    # The GPU is busy with training: resuming would fight the trainer
    assert admin.post("/api/system/inference/resume").status_code == 409
    assert as_user("config.cameras").post("/api/system/inference/pause", json={}).status_code == 403


def _dataset(db):
    ds = DatasetVersion(name="tmp", s3_prefix="datasets/tmp", status="ready")
    db.add(ds)
    db.flush()
    return ds.id
