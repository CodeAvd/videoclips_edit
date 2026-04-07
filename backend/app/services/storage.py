import hashlib
import json
import shutil
from collections.abc import AsyncIterable
from contextlib import suppress
from io import BytesIO
from dataclasses import dataclass
from datetime import timedelta
from functools import lru_cache
from pathlib import Path
from uuid import uuid4

from minio import Minio
from minio.error import S3Error

from app.core.config import Settings, get_settings


class StorageError(RuntimeError):
    pass


@dataclass(frozen=True)
class StorageObjectMetadata:
    storage_key: str
    size_bytes: int
    sha256: str | None
    content_type: str | None
    backend: str


class StorageService:
    def create_upload_url(self, *, upload_id: str, storage_key: str) -> str | None:
        raise NotImplementedError

    def supports_direct_app_upload(self) -> bool:
        return False

    def write_bytes(self, *, storage_key: str, content_type: str, body: bytes) -> StorageObjectMetadata:
        raise StorageError("Active storage backend does not support direct writes.")

    def write_json(self, *, storage_key: str, payload: dict | list, content_type: str = "application/json") -> StorageObjectMetadata:
        body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return self.write_bytes(storage_key=storage_key, content_type=content_type, body=body)

    def write_upload_bytes(self, *, storage_key: str, content_type: str, body: bytes) -> None:
        self.write_bytes(storage_key=storage_key, content_type=content_type, body=body)

    async def write_upload_stream(
        self,
        *,
        storage_key: str,
        content_type: str,
        chunks: AsyncIterable[bytes],
    ) -> None:
        raise StorageError("Active storage backend does not support streamed app uploads.")

    def read_bytes(self, *, storage_key: str) -> bytes:
        raise NotImplementedError

    def read_metadata(self, *, storage_key: str) -> StorageObjectMetadata:
        raise NotImplementedError

    def read_upload_metadata(self, *, storage_key: str) -> StorageObjectMetadata:
        return self.read_metadata(storage_key=storage_key)

    def local_path_for_key(self, *, storage_key: str) -> Path | None:
        return None

    def materialize_to_path(self, *, storage_key: str, destination: Path) -> Path:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(self.read_bytes(storage_key=storage_key))
        return destination

    def read_json(self, *, storage_key: str) -> dict | list:
        payload = self.read_bytes(storage_key=storage_key)
        return json.loads(payload.decode("utf-8"))


class FilesystemStorageService(StorageService):
    def __init__(self, settings: Settings):
        self._settings = settings
        self._root = Path(settings.local_storage_dir).expanduser().resolve()
        self._root.mkdir(parents=True, exist_ok=True)

    def create_upload_url(self, *, upload_id: str, storage_key: str) -> str:
        return f"{self._settings.app_base_url.rstrip('/')}{self._settings.api_v1_prefix}/uploads/{upload_id}/content"

    def supports_direct_app_upload(self) -> bool:
        return True

    def write_bytes(self, *, storage_key: str, content_type: str, body: bytes) -> StorageObjectMetadata:
        target = self._path_for_key(storage_key)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(body)
        metadata_path = self._metadata_path_for_key(storage_key)
        metadata_path.write_text(json.dumps({"content_type": content_type}), encoding="utf-8")
        return self.read_metadata(storage_key=storage_key)

    async def write_upload_stream(
        self,
        *,
        storage_key: str,
        content_type: str,
        chunks: AsyncIterable[bytes],
    ) -> None:
        target = self._path_for_key(storage_key)
        target.parent.mkdir(parents=True, exist_ok=True)
        temp_target = target.with_name(f".{target.name}.{uuid4().hex}.part")
        try:
            with temp_target.open("wb") as handle:
                async for chunk in chunks:
                    if not chunk:
                        continue
                    handle.write(chunk)
            temp_target.replace(target)
            metadata_path = self._metadata_path_for_key(storage_key)
            metadata_path.write_text(json.dumps({"content_type": content_type}), encoding="utf-8")
        except Exception:
            with suppress(FileNotFoundError):
                temp_target.unlink()
            raise

    def read_metadata(self, *, storage_key: str) -> StorageObjectMetadata:
        target = self._path_for_key(storage_key)
        if not target.exists():
            raise StorageError(f"Stored object does not exist for key {storage_key}.")
        payload = target.read_bytes()
        sha256 = hashlib.sha256(payload).hexdigest()
        metadata_path = self._metadata_path_for_key(storage_key)
        content_type = None
        if metadata_path.exists():
            content_type = json.loads(metadata_path.read_text(encoding="utf-8")).get("content_type")
        return StorageObjectMetadata(
            storage_key=storage_key,
            size_bytes=target.stat().st_size,
            sha256=sha256,
            content_type=content_type,
            backend="filesystem",
        )

    def read_bytes(self, *, storage_key: str) -> bytes:
        target = self._path_for_key(storage_key)
        if not target.exists():
            raise StorageError(f"Stored object does not exist for key {storage_key}.")
        return target.read_bytes()

    def local_path_for_key(self, *, storage_key: str) -> Path | None:
        target = self._path_for_key(storage_key)
        if not target.exists():
            raise StorageError(f"Stored object does not exist for key {storage_key}.")
        return target

    def materialize_to_path(self, *, storage_key: str, destination: Path) -> Path:
        source = self.local_path_for_key(storage_key=storage_key)
        if source is None:
            return super().materialize_to_path(storage_key=storage_key, destination=destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
        return destination

    def _path_for_key(self, storage_key: str) -> Path:
        sanitized = storage_key.lstrip("/")
        candidate = (self._root / sanitized).resolve()
        if self._root not in candidate.parents and candidate != self._root:
            raise StorageError(f"Storage key escapes configured root: {storage_key}")
        return candidate

    def _metadata_path_for_key(self, storage_key: str) -> Path:
        target = self._path_for_key(storage_key)
        return target.with_name(f"{target.name}.meta.json")


class MinioStorageService(StorageService):
    def __init__(self, settings: Settings):
        self._settings = settings
        self._client = Minio(
            endpoint=settings.minio_endpoint,
            access_key=settings.minio_access_key,
            secret_key=settings.minio_secret_key,
            secure=settings.minio_secure,
        )

    def create_upload_url(self, *, upload_id: str, storage_key: str) -> str:
        self._ensure_bucket()
        return self._client.presigned_put_object(
            bucket_name=self._settings.storage_bucket,
            object_name=storage_key,
            expires=timedelta(seconds=self._settings.storage_presign_expiry_seconds),
        )

    def write_bytes(self, *, storage_key: str, content_type: str, body: bytes) -> StorageObjectMetadata:
        self._ensure_bucket()
        sha256 = hashlib.sha256(body).hexdigest()
        self._client.put_object(
            bucket_name=self._settings.storage_bucket,
            object_name=storage_key,
            data=BytesIO(body),
            length=len(body),
            content_type=content_type,
            metadata={"sha256": sha256},
        )
        return StorageObjectMetadata(
            storage_key=storage_key,
            size_bytes=len(body),
            sha256=sha256,
            content_type=content_type,
            backend="minio",
        )

    def read_metadata(self, *, storage_key: str) -> StorageObjectMetadata:
        self._ensure_bucket()
        try:
            stat = self._client.stat_object(self._settings.storage_bucket, storage_key)
        except S3Error as exc:
            raise StorageError(f"Stored object does not exist for key {storage_key}.") from exc
        return StorageObjectMetadata(
            storage_key=storage_key,
            size_bytes=int(stat.size),
            sha256=stat.metadata.get("x-amz-meta-sha256"),
            content_type=stat.content_type,
            backend="minio",
        )

    def read_bytes(self, *, storage_key: str) -> bytes:
        self._ensure_bucket()
        try:
            response = self._client.get_object(self._settings.storage_bucket, storage_key)
        except S3Error as exc:
            raise StorageError(f"Stored object does not exist for key {storage_key}.") from exc
        try:
            return response.read()
        finally:
            response.close()
            response.release_conn()

    def materialize_to_path(self, *, storage_key: str, destination: Path) -> Path:
        self._ensure_bucket()
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._client.fget_object(self._settings.storage_bucket, storage_key, str(destination))
        except S3Error as exc:
            raise StorageError(f"Stored object does not exist for key {storage_key}.") from exc
        return destination

    def _ensure_bucket(self) -> None:
        if self._client.bucket_exists(self._settings.storage_bucket):
            return
        self._client.make_bucket(self._settings.storage_bucket)


@lru_cache
def get_storage_service() -> StorageService:
    settings = get_settings()
    if settings.storage_backend == "minio":
        return MinioStorageService(settings)
    return FilesystemStorageService(settings)
