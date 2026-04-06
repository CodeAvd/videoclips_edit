from uuid import UUID

from sqlalchemy import select

from app.models.job import SourceVideo, SourceVideoArtifact
from app.services.source_video_artifacts import get_preferred_video_artifact
from flow_helpers import run_job_pipeline_smoke


async def test_ingest_keeps_source_asset_and_registers_canonical_video_role(
    client,
    actor_headers,
    session_factory,
    storage_root,
    monkeypatch,
) -> None:
    context = await run_job_pipeline_smoke(
        client=client,
        actor_headers=actor_headers,
        session_factory=session_factory,
        storage_root=storage_root,
        monkeypatch=monkeypatch,
    )
    source_video_id = UUID(str(context["source_video_id"]))

    async with session_factory() as session:
        source_video = await session.get(SourceVideo, source_video_id)
        artifact_links = (
            await session.execute(
                select(SourceVideoArtifact).where(SourceVideoArtifact.source_video_id == source_video_id)
            )
        ).scalars().all()

    by_role = {link.role: link.artifact_id for link in artifact_links}
    assert source_video is not None
    assert by_role["source_asset"] == source_video.canonical_asset_id
    assert by_role["canonical_video"] == by_role["proxy_video"]
    assert by_role["canonical_video"] != source_video.canonical_asset_id
    assert "normalized_audio" in by_role
    assert "thumbnails" in by_role

    async with session_factory() as session:
        preferred_video_artifact = await get_preferred_video_artifact(session, source_video_id=source_video_id)

    assert preferred_video_artifact.id == by_role["canonical_video"]
