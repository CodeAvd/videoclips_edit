from uuid import UUID, uuid4

from app.api.v1.endpoints.jobs import build_job_checksum
from app.models.enums import Platform
from app.schemas.job import CreateJobRequest


def build_payload(source_video_id: UUID, target_platforms: list[Platform]) -> CreateJobRequest:
    return CreateJobRequest(
        source_video_id=source_video_id,
        target_platforms=target_platforms,
        target_final_clip_count=4,
        publish_mode="approval_gated",
        prompt_version="v1",
        scoring_policy_version="v1",
        shortlist_target_count=8,
    )


def test_build_job_checksum_is_order_independent_for_target_platforms() -> None:
    source_video_id = uuid4()
    payload_a = build_payload(source_video_id, [Platform.youtube_shorts, Platform.instagram_reels, Platform.tiktok])
    payload_b = build_payload(source_video_id, [Platform.tiktok, Platform.youtube_shorts, Platform.instagram_reels])

    assert build_job_checksum(payload_a) == build_job_checksum(payload_b)
