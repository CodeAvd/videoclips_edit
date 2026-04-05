from sqlalchemy import select

from app.models.job import ApiIdempotencyKey

from test_jobs_worker_flow import create_uploaded_source_video


async def test_create_job_replays_completed_response_for_same_idempotency_key(client, actor_headers, session_factory) -> None:
    _, source_video_id = await create_uploaded_source_video(client, actor_headers)
    headers = {**actor_headers, "Idempotency-Key": "job-idempotent-1"}
    payload = {
        "source_video_id": source_video_id,
        "target_platforms": ["youtube_shorts"],
        "target_final_clip_count": 3,
        "publish_mode": "approval_gated",
        "prompt_version": "v1",
        "scoring_policy_version": "v1",
        "shortlist_target_count": 6,
    }

    first_response = await client.post("/api/v1/jobs", headers=headers, json=payload)
    second_response = await client.post("/api/v1/jobs", headers=headers, json=payload)

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    assert first_response.json() == second_response.json()

    async with session_factory() as session:
        records = (await session.execute(select(ApiIdempotencyKey))).scalars().all()
        assert len(records) == 2


async def test_create_job_rejects_same_idempotency_key_with_different_payload(client, actor_headers) -> None:
    _, source_video_id = await create_uploaded_source_video(client, actor_headers)
    headers = {**actor_headers, "Idempotency-Key": "job-idempotent-conflict"}

    first_response = await client.post(
        "/api/v1/jobs",
        headers=headers,
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
    assert first_response.status_code == 200

    second_response = await client.post(
        "/api/v1/jobs",
        headers=headers,
        json={
            "source_video_id": source_video_id,
            "target_platforms": ["youtube_shorts", "instagram_reels"],
            "target_final_clip_count": 3,
            "publish_mode": "approval_gated",
            "prompt_version": "v1",
            "scoring_policy_version": "v1",
            "shortlist_target_count": 6,
        },
    )
    assert second_response.status_code == 409
    assert second_response.json()["code"] == "idempotency_conflict"
