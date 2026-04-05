import hashlib
from pathlib import Path
from urllib.parse import urlparse


async def test_upload_session_round_trip(client, actor_headers, storage_root) -> None:
    body = b"hello shorts engine"
    sha256 = hashlib.sha256(body).hexdigest()

    create_response = await client.post(
        "/api/v1/uploads",
        headers=actor_headers,
        json={
            "filename": "episode.mp4",
            "content_type": "video/mp4",
            "size_bytes": len(body),
            "sha256": sha256,
        },
    )
    assert create_response.status_code == 200
    created = create_response.json()
    assert created["status"] == "created"
    assert created["upload_url"].endswith(f"/api/v1/uploads/{created['id']}/content")

    upload_path = urlparse(created["upload_url"]).path
    upload_response = await client.put(
        upload_path,
        headers={**actor_headers, "Content-Type": "application/octet-stream"},
        content=body,
    )
    assert upload_response.status_code == 204

    stored_path = Path(storage_root) / created["storage_key"]
    assert stored_path.exists()
    assert stored_path.read_bytes() == body

    complete_response = await client.post(
        f"/api/v1/uploads/{created['id']}/complete",
        headers={**actor_headers, "Idempotency-Key": "upload-complete-roundtrip"},
        json={"sha256": sha256, "size_bytes": len(body)},
    )
    assert complete_response.status_code == 200
    completed = complete_response.json()
    assert completed["status"] == "completed"
    assert completed["completed_artifact_id"] is not None
    assert completed["upload_url"] is None

    get_response = await client.get(f"/api/v1/uploads/{created['id']}", headers=actor_headers)
    assert get_response.status_code == 200
    fetched = get_response.json()
    assert fetched["status"] == "completed"
    assert fetched["upload_url"] is None


async def test_upload_complete_rejects_checksum_mismatch(client, actor_headers) -> None:
    body = b"real-content"
    declared_sha = hashlib.sha256(body).hexdigest()

    create_response = await client.post(
        "/api/v1/uploads",
        headers=actor_headers,
        json={
            "filename": "bad.mp4",
            "content_type": "video/mp4",
            "size_bytes": len(body),
            "sha256": declared_sha,
        },
    )
    upload_id = create_response.json()["id"]
    upload_path = urlparse(create_response.json()["upload_url"]).path
    await client.put(
        upload_path,
        headers={**actor_headers, "Content-Type": "application/octet-stream"},
        content=body,
    )

    complete_response = await client.post(
        f"/api/v1/uploads/{upload_id}/complete",
        headers={**actor_headers, "Idempotency-Key": "upload-complete-mismatch"},
        json={"sha256": "0" * 64, "size_bytes": len(body)},
    )
    assert complete_response.status_code == 422
    assert complete_response.json()["code"] == "validation_error"


async def test_upload_complete_requires_idempotency_key(client, actor_headers) -> None:
    body = b"missing-idempotency"
    sha256 = hashlib.sha256(body).hexdigest()

    create_response = await client.post(
        "/api/v1/uploads",
        headers=actor_headers,
        json={
            "filename": "missing-idempotency.mp4",
            "content_type": "video/mp4",
            "size_bytes": len(body),
            "sha256": sha256,
        },
    )
    upload_id = create_response.json()["id"]
    upload_path = urlparse(create_response.json()["upload_url"]).path
    await client.put(
        upload_path,
        headers={**actor_headers, "Content-Type": "application/octet-stream"},
        content=body,
    )

    complete_response = await client.post(
        f"/api/v1/uploads/{upload_id}/complete",
        headers=actor_headers,
        json={"sha256": sha256, "size_bytes": len(body)},
    )
    assert complete_response.status_code == 400
    assert complete_response.json()["code"] == "validation_error"
