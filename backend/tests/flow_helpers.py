import hashlib
from pathlib import Path
import subprocess
import tempfile
from urllib.parse import urlparse

from app.services import worker_runtime


def build_test_video_bytes() -> bytes:
    with tempfile.TemporaryDirectory(prefix="ai-shorts-test-media-") as temp_dir:
        output_path = Path(temp_dir) / "sample.mp4"
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-f",
                "lavfi",
                "-i",
                "color=c=black:s=320x240:d=6",
                "-f",
                "lavfi",
                "-i",
                "sine=frequency=1000:duration=6",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                "-shortest",
                str(output_path),
            ],
            check=True,
            capture_output=True,
        )
        return output_path.read_bytes()


async def create_uploaded_source_video(client, actor_headers) -> tuple[str, str]:
    brand_response = await client.post(
        "/api/v1/brand-profiles",
        headers=actor_headers,
        json={
            "name": "Test Brand",
            "language": "en",
            "caption_style_defaults": {},
            "overlay_policy": {},
            "music_policy": {},
            "platform_defaults": {},
        },
    )
    assert brand_response.status_code == 200
    brand_id = brand_response.json()["id"]

    body = build_test_video_bytes()
    sha256 = hashlib.sha256(body).hexdigest()
    upload_response = await client.post(
        "/api/v1/uploads",
        headers=actor_headers,
        json={
            "filename": "source.mp4",
            "content_type": "video/mp4",
            "size_bytes": len(body),
            "sha256": sha256,
        },
    )
    assert upload_response.status_code == 200
    upload_payload = upload_response.json()
    await client.put(
        urlparse(upload_payload["upload_url"]).path,
        headers={**actor_headers, "Content-Type": "application/octet-stream"},
        content=body,
    )
    complete_response = await client.post(
        f"/api/v1/uploads/{upload_payload['id']}/complete",
        headers={**actor_headers, "Idempotency-Key": "source-upload-complete"},
        json={"sha256": sha256, "size_bytes": len(body)},
    )
    assert complete_response.status_code == 200
    artifact_id = complete_response.json()["completed_artifact_id"]

    source_response = await client.post(
        "/api/v1/source-videos",
        headers=actor_headers,
        json={
            "artifact_id": artifact_id,
            "brand_profile_id": brand_id,
            "rights_attestation": True,
            "source_type": "uploaded_asset",
            "duration_ms": 2_700_000,
            "language": "en",
            "speaker_count_estimate": 1,
        },
    )
    assert source_response.status_code == 200
    return brand_id, source_response.json()["id"]


async def create_job(client, actor_headers, source_video_id: str) -> dict:
    response = await client.post(
        "/api/v1/jobs",
        headers={**actor_headers, "Idempotency-Key": f"job-create-{source_video_id}"},
        json={
            "source_video_id": source_video_id,
            "target_platforms": ["youtube_shorts"],
            "target_final_clip_count": 3,
            "publish_mode": "approval_gated",
            "prompt_version": "v1",
            "scoring_policy_version": "v1",
            "shortlist_target_count": 6,
        },
    )
    assert response.status_code == 200
    return response.json()


async def run_job_pipeline_smoke(
    *,
    client,
    actor_headers,
    session_factory,
    storage_root: str,
    monkeypatch,
) -> dict[str, object]:
    _, source_video_id = await create_uploaded_source_video(client, actor_headers)

    payload = {
        "source_video_id": source_video_id,
        "target_platforms": ["instagram_reels", "youtube_shorts"],
        "target_final_clip_count": 3,
        "publish_mode": "approval_gated",
        "prompt_version": "v1",
        "scoring_policy_version": "v1",
        "shortlist_target_count": 6,
    }
    create_response = await client.post(
        "/api/v1/jobs",
        headers={**actor_headers, "Idempotency-Key": "job-create-primary"},
        json=payload,
    )
    assert create_response.status_code == 200
    first_job = create_response.json()

    dedupe_response = await client.post(
        "/api/v1/jobs",
        headers={**actor_headers, "Idempotency-Key": "job-create-natural-dedupe"},
        json={**payload, "target_platforms": ["youtube_shorts", "instagram_reels"]},
    )
    assert dedupe_response.status_code == 200
    assert dedupe_response.json()["job_id"] == first_job["job_id"]

    monkeypatch.setattr(worker_runtime, "SessionLocal", session_factory)
    processed = 0
    while await worker_runtime.process_next_outbox_event(worker_id="test-worker"):
        processed += 1
        if processed > 10:
            raise AssertionError("Worker loop processed too many events for the smoke pipeline.")

    assert processed == 5

    job_response = await client.get(f"/api/v1/jobs/{first_job['job_id']}", headers=actor_headers)
    assert job_response.status_code == 200
    assert job_response.json()["status"] == "awaiting_shortlist_review"

    stage_runs_response = await client.get(f"/api/v1/jobs/{first_job['job_id']}/stage-runs", headers=actor_headers)
    assert stage_runs_response.status_code == 200
    stage_runs = {item["stage_name"]: item for item in stage_runs_response.json()["items"]}
    assert stage_runs["intake"]["status"] == "succeeded"
    assert stage_runs["ingest"]["status"] == "succeeded"
    assert stage_runs["transcript"]["status"] == "succeeded"
    assert stage_runs["feature_extract"]["status"] == "succeeded"
    assert stage_runs["ranking"]["status"] == "succeeded"

    segments_response = await client.get(f"/api/v1/jobs/{first_job['job_id']}/transcript-segments", headers=actor_headers)
    assert segments_response.status_code == 200
    assert len(segments_response.json()["items"]) > 0

    words_response = await client.get(f"/api/v1/jobs/{first_job['job_id']}/transcript-words", headers=actor_headers)
    assert words_response.status_code == 200
    assert len(words_response.json()["items"]) > 0

    candidates_response = await client.get(f"/api/v1/jobs/{first_job['job_id']}/candidate-clips", headers=actor_headers)
    assert candidates_response.status_code == 200
    candidate_items = candidates_response.json()["items"]
    assert 5 <= len(candidate_items) <= 80

    candidate_detail = await client.get(f"/api/v1/candidate-clips/{candidate_items[0]['id']}", headers=actor_headers)
    assert candidate_detail.status_code == 200
    assert candidate_detail.json()["job_id"] == first_job["job_id"]

    storage_base = Path(storage_root)
    assert (storage_base / f"derived/{source_video_id}/audio.wav").exists()
    assert (storage_base / f"derived/{source_video_id}/proxy.mp4").exists()
    assert (storage_base / f"derived/{source_video_id}/thumbnails.json").exists()
    assert (storage_base / f"logs/{first_job['job_id']}/{stage_runs['ingest']['id']}/ingest.json").exists()
    assert (storage_base / f"logs/{first_job['job_id']}/{stage_runs['transcript']['id']}/transcript.json").exists()
    assert (storage_base / f"logs/{first_job['job_id']}/{stage_runs['feature_extract']['id']}/pause_track.json").exists()
    assert (storage_base / f"logs/{first_job['job_id']}/{stage_runs['ranking']['id']}/ranking_summary.json").exists()

    return {
        "job_id": first_job["job_id"],
        "source_video_id": source_video_id,
        "stage_runs": stage_runs,
        "candidate_items": candidate_items,
    }
