from pathlib import Path

import pytest

from app.core.config import Settings
from app.services.storage import FilesystemStorageService, StorageError


def build_settings(storage_dir: Path) -> Settings:
    return Settings(
        _env_file=None,
        local_storage_dir=str(storage_dir),
        app_base_url="http://localhost:8000",
        storage_backend="filesystem",
    )


def test_filesystem_storage_roundtrip(tmp_path: Path) -> None:
    service = FilesystemStorageService(build_settings(tmp_path))

    metadata = service.write_bytes(
        storage_key="uploads/session-1/video.bin",
        content_type="application/octet-stream",
        body=b"hello-shorts",
    )

    assert metadata.storage_key == "uploads/session-1/video.bin"
    assert metadata.size_bytes == len(b"hello-shorts")
    assert metadata.content_type == "application/octet-stream"
    assert metadata.backend == "filesystem"

    stored_path = tmp_path / "uploads" / "session-1" / "video.bin"
    assert stored_path.exists()

    reloaded = service.read_metadata(storage_key="uploads/session-1/video.bin")
    assert reloaded.sha256 == metadata.sha256
    assert reloaded.size_bytes == metadata.size_bytes


def test_filesystem_storage_rejects_path_escape(tmp_path: Path) -> None:
    service = FilesystemStorageService(build_settings(tmp_path))

    with pytest.raises(StorageError, match="escapes configured root"):
        service.write_bytes(
            storage_key="../escape.bin",
            content_type="application/octet-stream",
            body=b"bad",
        )


async def test_filesystem_storage_stream_upload(tmp_path: Path) -> None:
    service = FilesystemStorageService(build_settings(tmp_path))

    async def chunk_stream():
        for chunk in (b"hello", b"-", b"shorts"):
            yield chunk

    await service.write_upload_stream(
        storage_key="uploads/session-2/video.bin",
        content_type="application/octet-stream",
        chunks=chunk_stream(),
    )

    stored_path = tmp_path / "uploads" / "session-2" / "video.bin"
    assert stored_path.exists()
    assert stored_path.read_bytes() == b"hello-shorts"
