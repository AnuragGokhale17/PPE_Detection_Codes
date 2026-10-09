import importlib
import sys

import pytest

import worker_common as wc


def test_local_storage_round_trip(tmp_path):
    store = wc.LocalStorage(tmp_path)
    store.put_bytes("datasets/v1/images/train/1.jpg", b"img1", "image/jpeg")
    store.put_bytes("datasets/v1/labels/train/1.txt", b"0 0.5 0.5 0.1 0.1\n", "text/plain")
    store.put_bytes("datasets/v1/data.yaml", b"names: {}", "text/yaml")
    store.put_bytes("datasets/v2/data.yaml", b"other", "text/yaml")

    assert store.exists("datasets/v1/images/train/1.jpg")
    assert not store.exists("datasets/v1/images/train/2.jpg")
    assert store.get_bytes("datasets/v1/labels/train/1.txt").startswith(b"0 0.5")

    dest = tmp_path / "mirror"
    count = store.download_prefix("datasets/v1/", dest)
    assert count == 3
    assert (dest / "images" / "train" / "1.jpg").read_bytes() == b"img1"
    assert (dest / "data.yaml").read_bytes() == b"names: {}"
    assert store.download_prefix("datasets/missing/", tmp_path / "none") == 0


def test_local_storage_rejects_escaping_keys(tmp_path):
    store = wc.LocalStorage(tmp_path / "root")
    with pytest.raises(ValueError):
        store.put_bytes("../outside.jpg", b"x")


def test_get_storage_without_credentials_is_local(monkeypatch, tmp_path):
    monkeypatch.delenv("AWS_ACCESS_KEY_ID", raising=False)
    monkeypatch.delenv("AWS_SECRET_ACCESS_KEY", raising=False)
    monkeypatch.setenv("LOCAL_STORAGE_DIR", str(tmp_path))
    store = wc.get_storage()
    assert store.kind == "local" and store.root == tmp_path


def test_db_params_require_credentials(monkeypatch):
    monkeypatch.delenv("DB_PASS", raising=False)
    monkeypatch.setenv("DB_USER", "u")
    monkeypatch.setenv("DB_NAME", "ppes")
    with pytest.raises(RuntimeError, match="DB_PASS"):
        wc.db_params()  # no hard-coded password fallback any more


def test_resolve_repo_path(tmp_path):
    assert wc.resolve_repo_path("model/best12classes.pt") == wc.REPO_DIR / "model" / "best12classes.pt"
    assert wc.resolve_repo_path(str(tmp_path / "w.pt")) == tmp_path / "w.pt"


def test_trainer_module_imports_without_ml_or_db_libraries():
    """Polling/claiming logic must be importable where ultralytics/torch/psycopg2 are absent."""
    sys.modules.pop("trainer", None)
    trainer = importlib.import_module("trainer")
    assert issubclass(trainer.TrainingCancelled, Exception)
    assert trainer.RUNS_DIR == wc.REPO_DIR / "training" / "runs"
