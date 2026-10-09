import os
import tempfile
from pathlib import Path

# Configure before anything imports app.* (settings and engine are created at import)
_db_dir = tempfile.mkdtemp(prefix="ppe-api-test-")
os.environ["DATABASE_URL"] = f"sqlite:///{Path(_db_dir) / 'test.db'}"
os.environ["SECRET_KEY"] = "test-secret-key-for-unit-tests-only-0123456789"
os.environ["COOKIE_SECURE"] = "false"
os.environ["APP_BASE_URL"] = "http://frontend.test"
os.environ["LOCAL_STORAGE_DIR"] = str(Path(_db_dir) / "storage")
# Never talk to a real MinIO from tests
os.environ.pop("AWS_ACCESS_KEY_ID", None)
os.environ.pop("AWS_SECRET_ACCESS_KEY", None)

import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.core.config import BACKEND_DIR  # noqa: E402
from app.db.session import SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.services import accounts  # noqa: E402

PASSWORD = "Correct-Horse-42!"


@pytest.fixture(scope="session", autouse=True)
def migrated_db():
    # Running the real migrations doubles as a test that they apply cleanly
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    command.upgrade(cfg, "head")
    yield
    engine.dispose()


TRANSIENT_TABLES = (
    "dataset_samples",
    "training_runs",
    "dataset_versions",
    "sample_labels",
    "samples",
    "alert_recipients",
    "camera_ppe",
    "cameras",
    "production_houses",
    "plants",
    "worker_heartbeats",
    "ppes",
    "ppes_emails_records",
    "camera_health",
    "user_permissions",
    "auth_otps",
    "password_history",
    "otps",
    "activity_logs",
    "users",
)


@pytest.fixture(autouse=True)
def clean_tables(migrated_db):
    yield
    with engine.begin() as conn:
        for table in TRANSIENT_TABLES:
            conn.exec_driver_sql(f"DELETE FROM {table}")
        # Put the seeded registry, models and runtime state back the way 0003 left them
        conn.exec_driver_sql("DELETE FROM model_classes WHERE class_id > 11")
        conn.exec_driver_sql("DELETE FROM ppe_items WHERE id > 6")
        conn.exec_driver_sql("DELETE FROM model_versions WHERE id > 1")
        conn.exec_driver_sql("UPDATE model_versions SET is_active = 1")
        conn.exec_driver_sql("UPDATE model_classes SET enabled = 1")
        conn.exec_driver_sql("UPDATE ppe_items SET enabled = 1")
        conn.exec_driver_sql(
            "UPDATE runtime_state SET config_version = 1, inference_paused = 0, pause_reason = NULL, active_model_id = 1"
        )


@pytest.fixture
def storage():
    from app.services.storage import get_storage

    return get_storage()


@pytest.fixture
def db():
    with SessionLocal() as session:
        yield session


@pytest.fixture
def make_user(db):
    def _make(email="jane.doe@solargroup.com", role="user", password=PASSWORD):
        user, error = accounts.create_user(db, email, password, role)
        assert error is None, error
        return user

    return _make


class Mailbox:
    def __init__(self):
        self.otps: dict[str, str] = {}
        self.reset_links: dict[str, str] = {}


@pytest.fixture
def mailbox(monkeypatch):
    box = Mailbox()

    def fake_otp(to, code, ttl):
        box.otps[to] = code
        return True

    def fake_reset(to, link, ttl):
        box.reset_links[to] = link
        return True

    monkeypatch.setattr("app.routers.auth.send_otp_email", fake_otp)
    monkeypatch.setattr("app.routers.auth.send_password_reset_email", fake_reset)
    return box


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


@pytest.fixture
def login(mailbox):
    """Runs the full password + OTP flow on a client; returns the /verify-otp response."""

    def _login(client, email="jane.doe@solargroup.com", password=PASSWORD):
        r = client.post("/api/auth/login", json={"email": email, "password": password})
        assert r.status_code == 200, r.text
        r = client.post("/api/auth/verify-otp", json={"otp": mailbox.otps[email]})
        assert r.status_code == 200, r.text
        return r

    return _login


@pytest.fixture
def as_user(client, make_user, login, db):
    """Signs a fresh client in as a user holding exactly the given permissions."""
    from app.db.models import UserPermission

    def _as(*permissions, role="user", email=None):
        email = email or f"user.{'-'.join(p.replace('.', '_') for p in permissions) or role}@solargroup.com"
        user = make_user(email, role=role)
        for p in permissions:
            db.add(UserPermission(user_id=user.id, permission=p))
        db.commit()
        c = TestClient(app)
        login(c, email)
        return c

    return _as


def jpeg_bytes(width=64, height=36, color=(120, 130, 140)) -> bytes:
    import io

    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (width, height), color).save(buf, format="JPEG")
    return buf.getvalue()
