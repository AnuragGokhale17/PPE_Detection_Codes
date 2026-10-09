"""
Shared plumbing for the GPU-server workers (inference.py, trainer.py, cooldown.py,
camera_status_mail.py): environment, PostgreSQL pool, object storage, heartbeats.

psycopg2 and boto3 are imported lazily so this module (and its local-storage backend)
stays importable in test environments that do not have them.
"""
import json
import logging
import os
import socket
import threading
from collections import namedtuple
from contextlib import contextmanager
from pathlib import Path

from dotenv import load_dotenv

from worker_logic import normalize_class_name  # noqa: F401  (re-exported for the workers)

__all__ = ["normalize_class_name"]

REPO_DIR = Path(__file__).resolve().parent
load_dotenv(REPO_DIR / ".env")

log = logging.getLogger("workers")


def env_bool(name, default=False):
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


def env_float(name, default):
    try:
        return float(os.getenv(name, default))
    except (TypeError, ValueError):
        return float(default)


def resolve_repo_path(path):
    """model_versions.weights_path is stored relative to the repository root."""
    p = Path(path)
    return p if p.is_absolute() else REPO_DIR / p


# ==============================================================================
# DATABASE
# ==============================================================================
def db_params():
    missing = [k for k in ("DB_USER", "DB_PASS", "DB_NAME") if not os.getenv(k)]
    if missing:
        raise RuntimeError(f"Missing database settings in .env: {', '.join(missing)}")
    return {
        "host": os.getenv("DB_HOST", "localhost"),
        "port": os.getenv("DB_PORT", "5432"),
        "user": os.getenv("DB_USER"),
        "password": os.getenv("DB_PASS"),
        "database": os.getenv("DB_NAME"),
        "connect_timeout": 5,
    }


def connect():
    """A single standalone connection (for the low-traffic daemons)."""
    import psycopg2

    return psycopg2.connect(**db_params())


class DbPool:
    """ThreadedConnectionPool with a leased-connection context manager. Falls back to a
    direct connection when the pool is exhausted, like the old get_db_connection()."""

    def __init__(self, minconn=2, maxconn=20):
        self.minconn = minconn
        self.maxconn = maxconn
        self._pool = None
        self._lock = threading.Lock()

    def _ensure(self):
        from psycopg2 import pool

        with self._lock:
            if self._pool is None or self._pool.closed:
                self._pool = pool.ThreadedConnectionPool(self.minconn, self.maxconn, **db_params())
                log.info("PostgreSQL pool ready (maxconn=%s).", self.maxconn)
        return self._pool

    @contextmanager
    def connection(self):
        conn, pooled = None, False
        try:
            pool_ = self._ensure()
            conn = pool_.getconn()
            pooled = True
        except Exception as e:  # pool exhausted or DB briefly unreachable
            log.debug("Pool lease failed (%s); using a direct connection.", e)
            try:
                conn = connect()
            except Exception as e2:
                log.error("Database connection error: %s", e2)
                yield None
                return
        try:
            yield conn
        finally:
            if pooled:
                try:
                    if conn.closed == 0 and conn.get_transaction_status() != 0:
                        conn.rollback()
                    self._pool.putconn(conn, close=bool(conn.closed))
                except Exception:
                    try:
                        conn.close()
                    except Exception:
                        pass
            elif conn is not None:
                try:
                    conn.close()
                except Exception:
                    pass

    def close(self):
        with self._lock:
            if self._pool is not None and not self._pool.closed:
                self._pool.closeall()


@contextmanager
def _borrow(conn_or_pool):
    if conn_or_pool is None:
        conn = connect()
        try:
            yield conn
        finally:
            conn.close()
    elif isinstance(conn_or_pool, DbPool):
        with conn_or_pool.connection() as conn:
            if conn is None:
                raise RuntimeError("Database unavailable")
            yield conn
    else:
        yield conn_or_pool


RuntimeState = namedtuple("RuntimeState", "config_version inference_paused pause_reason active_model_id")


def read_runtime_state(conn_or_pool=None):
    """The single runtime_state row (id=1), or None if the v2 migration has not run."""
    with _borrow(conn_or_pool) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT config_version, inference_paused, pause_reason, active_model_id "
                "FROM runtime_state WHERE id = 1"
            )
            row = cur.fetchone()
        conn.commit()
    return RuntimeState(*row) if row else None


def heartbeat(conn_or_pool, name, info):
    """Upserts worker_heartbeats so the portal can show whether the worker is alive."""
    from psycopg2.extras import Json

    payload = {"pid": os.getpid(), "host": socket.gethostname(), **(info or {})}
    try:
        with _borrow(conn_or_pool) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO worker_heartbeats (name, last_seen, info)
                    VALUES (%s, now(), %s)
                    ON CONFLICT (name) DO UPDATE SET last_seen = EXCLUDED.last_seen, info = EXCLUDED.info
                    """,
                    (name, Json(payload)),
                )
            conn.commit()
    except Exception as e:
        log.warning("Heartbeat for %s failed: %s", name, e)


# ==============================================================================
# OBJECT STORAGE
# ==============================================================================
class LocalStorage:
    """Object key a/b/c.jpg -> <root>/a/b/c.jpg. Used when MinIO is not configured,
    and as the fallback when an upload fails (same layout the API reads)."""

    kind = "local"

    def __init__(self, root=None):
        self.root = Path(root or os.getenv("LOCAL_STORAGE_DIR") or REPO_DIR / "var" / "storage")

    def _path(self, key):
        p = (self.root / key.lstrip("/")).resolve()
        if self.root.resolve() not in p.parents and p != self.root.resolve():
            raise ValueError(f"Key escapes the storage root: {key}")
        return p

    def put_bytes(self, key, data, content_type="application/octet-stream"):
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".part")
        tmp.write_bytes(data)
        os.replace(tmp, path)

    def get_bytes(self, key):
        return self._path(key).read_bytes()

    def exists(self, key):
        return self._path(key).is_file()

    def download_prefix(self, prefix, local_dir):
        src = self._path(prefix)
        dest = Path(local_dir)
        count = 0
        if not src.is_dir():
            return 0
        for f in src.rglob("*"):
            if f.is_file() and not f.name.endswith(".part"):
                target = dest / f.relative_to(src)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(f.read_bytes())
                count += 1
        return count


class S3Storage:
    kind = "s3"

    def __init__(self):
        import boto3
        import urllib3

        verify = env_bool("S3_VERIFY_TLS", False)
        if not verify:
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        self.bucket = os.getenv("BUCKET_NAME", "mybucket")
        self.client = boto3.client(
            "s3",
            endpoint_url=os.getenv("INTERNAL_S3_ENDPOINT_URL") or os.getenv("S3_ENDPOINT_URL"),
            aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
            aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
            verify=verify,
        )

    def put_bytes(self, key, data, content_type="application/octet-stream"):
        self.client.put_object(Bucket=self.bucket, Key=key, Body=data, ContentType=content_type)

    def get_bytes(self, key):
        return self.client.get_object(Bucket=self.bucket, Key=key)["Body"].read()

    def exists(self, key):
        from botocore.exceptions import ClientError

        try:
            self.client.head_object(Bucket=self.bucket, Key=key)
            return True
        except ClientError:
            return False

    def download_prefix(self, prefix, local_dir):
        prefix = prefix.rstrip("/") + "/"
        dest = Path(local_dir)
        count = 0
        paginator = self.client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
            for obj in page.get("Contents", []):
                rel = obj["Key"][len(prefix):]
                if not rel or rel.endswith("/"):
                    continue
                target = dest / rel
                target.parent.mkdir(parents=True, exist_ok=True)
                self.client.download_file(self.bucket, obj["Key"], str(target))
                count += 1
        return count


def get_storage():
    """MinIO when S3 credentials are configured, otherwise the local directory."""
    if os.getenv("AWS_ACCESS_KEY_ID") and os.getenv("AWS_SECRET_ACCESS_KEY"):
        try:
            return S3Storage()
        except Exception as e:
            log.error("S3 client initialisation failed (%s); using local storage.", e)
    return LocalStorage()


def json_dumps(value):
    return json.dumps(value, default=str)
