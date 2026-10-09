"""Object storage: MinIO when credentials are configured, a local directory otherwise.

Key layout (shared with inference.py / trainer.py):
    {month}/{event}.jpg                 annotated violation image (legacy)
    raw/{YYYY-MM}/{event}.jpg           clean frame for review and training
    samples/{YYYY-MM}/{uuid}.jpg        uploads and camera snapshots
    training-pool/images|labels/{id}    approved samples in YOLO layout
    datasets/{name}/...                 frozen dataset versions
"""
import logging
import shutil
from collections.abc import Iterator
from functools import lru_cache
from pathlib import Path
from typing import Protocol
from urllib.parse import unquote_plus, urlparse

from app.core.config import get_settings

log = logging.getLogger(__name__)


class StorageError(Exception):
    pass


class ObjectNotFound(StorageError):
    pass


class Storage(Protocol):
    def put_bytes(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> None: ...
    def get_bytes(self, key: str) -> bytes: ...
    def stream(self, key: str) -> Iterator[bytes]: ...
    def copy(self, src: str, dst: str) -> None: ...
    def exists(self, key: str) -> bool: ...
    def delete(self, key: str) -> None: ...


def _safe_key(key: str) -> str:
    key = key.lstrip("/")
    if not key or ".." in Path(key).parts:
        raise StorageError(f"Invalid object key: {key!r}")
    return key


class LocalStorage:
    def __init__(self, root: Path):
        self.root = Path(root)

    def _path(self, key: str) -> Path:
        return self.root / _safe_key(key)

    def put_bytes(self, key, data, content_type="application/octet-stream"):
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def get_bytes(self, key):
        try:
            return self._path(key).read_bytes()
        except FileNotFoundError as e:
            raise ObjectNotFound(key) from e

    def stream(self, key):
        path = self._path(key)
        if not path.is_file():
            raise ObjectNotFound(key)

        def chunks():
            with path.open("rb") as f:
                while chunk := f.read(64 * 1024):
                    yield chunk

        return chunks()

    def copy(self, src, dst):
        source = self._path(src)
        if not source.is_file():
            raise ObjectNotFound(src)
        target = self._path(dst)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)

    def exists(self, key):
        return self._path(key).is_file()

    def delete(self, key):
        self._path(key).unlink(missing_ok=True)


class MinioStorage:
    def __init__(self, endpoint_url: str, access_key: str, secret_key: str, bucket: str, verify_tls: bool):
        import urllib3
        from minio import Minio

        parsed = urlparse(endpoint_url)
        http_client = None
        if parsed.scheme == "https" and not verify_tls:
            # The plant MinIO uses a certificate issued for the public hostname, not 127.0.0.1
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            http_client = urllib3.PoolManager(cert_reqs="CERT_NONE", timeout=urllib3.Timeout(connect=5, read=60))
        self.client = Minio(
            parsed.netloc,
            access_key=access_key,
            secret_key=secret_key,
            secure=parsed.scheme == "https",
            http_client=http_client,
        )
        self.bucket = bucket

    def put_bytes(self, key, data, content_type="application/octet-stream"):
        import io

        self.client.put_object(self.bucket, _safe_key(key), io.BytesIO(data), len(data), content_type=content_type)

    def _get(self, key):
        from minio.error import S3Error

        try:
            return self.client.get_object(self.bucket, _safe_key(key))
        except S3Error as e:
            if e.code in ("NoSuchKey", "NoSuchObject"):
                raise ObjectNotFound(key) from e
            raise StorageError(str(e)) from e

    def get_bytes(self, key):
        response = self._get(key)
        try:
            return response.read()
        finally:
            response.close()
            response.release_conn()

    def stream(self, key):
        response = self._get(key)

        def chunks():
            try:
                yield from response.stream(64 * 1024)
            finally:
                response.close()
                response.release_conn()

        return chunks()

    def copy(self, src, dst):
        from minio.commonconfig import CopySource

        self.client.copy_object(self.bucket, _safe_key(dst), CopySource(self.bucket, _safe_key(src)))

    def exists(self, key):
        from minio.error import S3Error

        try:
            self.client.stat_object(self.bucket, _safe_key(key))
            return True
        except S3Error:
            return False

    def delete(self, key):
        self.client.remove_object(self.bucket, _safe_key(key))


@lru_cache
def get_storage() -> Storage:
    s = get_settings()
    if s.aws_access_key_id and s.aws_secret_access_key:
        return MinioStorage(
            s.internal_s3_endpoint_url, s.aws_access_key_id, s.aws_secret_access_key, s.bucket_name, s.s3_verify_tls
        )
    log.warning("No S3 credentials configured; storing objects under %s", s.local_storage_dir)
    return LocalStorage(s.local_storage_dir)


LOCAL_PREFIX = "local://"


def resolve(key: str) -> tuple[Storage, str]:
    """inference.py falls back to local disk when an upload fails and records the key as
    local://<key>. Those files live in LOCAL_STORAGE_DIR even when MinIO is configured."""
    if key.startswith(LOCAL_PREFIX):
        return LocalStorage(get_settings().local_storage_dir), key[len(LOCAL_PREFIX) :]
    return get_storage(), key


def stream_any(key: str) -> Iterator[bytes]:
    storage, k = resolve(key)
    return storage.stream(k)


def get_bytes_any(key: str) -> bytes:
    storage, k = resolve(key)
    return storage.get_bytes(k)


def copy_into_main(src: str, dst: str) -> None:
    """Copies any object (MinIO or local fallback) to `dst` in the main storage."""
    source, src_key = resolve(src)
    target = get_storage()
    if source is target or (isinstance(source, LocalStorage) and isinstance(target, LocalStorage) and source.root == target.root):
        target.copy(src_key, dst)
    else:
        target.put_bytes(dst, source.get_bytes(src_key), "image/jpeg")


def key_from_image_url(image_url: str | None) -> str | None:
    """Turns the URL inference.py stores in ppes.image_url back into an object key.

    https://host:9000/mybucket/october%2F2026-10-09101500_PP-25_AREA.jpg -> october/2026-..._AREA.jpg
    local://raw/2026-10/x.jpg                                            -> unchanged (see resolve())
    """
    if not image_url:
        return None
    if image_url.startswith(LOCAL_PREFIX):
        return image_url  # resolve() reads it from the local fallback directory
    path = urlparse(image_url).path.lstrip("/")
    bucket = get_settings().bucket_name
    if path.startswith(bucket + "/"):
        path = path[len(bucket) + 1 :]
    # inference.py quote_plus()-es the key, so '+' means space and %2F means '/'
    return unquote_plus(path) or None
