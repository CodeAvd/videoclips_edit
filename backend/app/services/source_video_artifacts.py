from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import select

from app.core.errors import AppError
from app.models.enums import SourceVideoArtifactRole
from app.models.job import ArtifactObject, SourceVideoArtifact, SourceVideoProvenance


@dataclass(slots=True)
class ResolvedSourceVideoArtifact:
    role: SourceVideoArtifactRole
    artifact: ArtifactObject
    attached_at: datetime


async def get_source_video_artifact(session, *, source_video_id: UUID, role: SourceVideoArtifactRole) -> ArtifactObject:
    result = await session.execute(
        select(ArtifactObject)
        .join(SourceVideoArtifact, SourceVideoArtifact.artifact_id == ArtifactObject.id)
        .where(
            SourceVideoArtifact.source_video_id == source_video_id,
            SourceVideoArtifact.role == role.value,
        )
        .order_by(SourceVideoArtifact.created_at.desc())
        .limit(1)
    )
    artifact = result.scalars().first()
    if artifact is None:
        raise AppError(
            code="artifact_not_found",
            message=f"Source video artifact not found for role {role.value}.",
            http_status=404,
        )
    return artifact


async def list_source_video_artifacts(session, *, source_video_id: UUID) -> list[ResolvedSourceVideoArtifact]:
    result = await session.execute(
        select(SourceVideoArtifact, ArtifactObject)
        .join(ArtifactObject, ArtifactObject.id == SourceVideoArtifact.artifact_id)
        .where(SourceVideoArtifact.source_video_id == source_video_id)
        .order_by(SourceVideoArtifact.role.asc(), SourceVideoArtifact.created_at.desc())
    )
    latest_by_role: dict[SourceVideoArtifactRole, ResolvedSourceVideoArtifact] = {}
    for link, artifact in result.all():
        role = SourceVideoArtifactRole(link.role)
        if role in latest_by_role:
            continue
        latest_by_role[role] = ResolvedSourceVideoArtifact(
            role=role,
            artifact=artifact,
            attached_at=link.created_at,
        )
    return [latest_by_role[role] for role in SourceVideoArtifactRole if role in latest_by_role]


async def list_source_video_provenance(session, *, source_video_id: UUID) -> list[SourceVideoProvenance]:
    result = await session.execute(
        select(SourceVideoProvenance)
        .where(SourceVideoProvenance.source_video_id == source_video_id)
        .order_by(SourceVideoProvenance.created_at.asc())
    )
    return list(result.scalars().all())


async def get_preferred_video_artifact(session, *, source_video_id: UUID) -> ArtifactObject:
    try:
        return await get_source_video_artifact(
            session,
            source_video_id=source_video_id,
            role=SourceVideoArtifactRole.canonical_video,
        )
    except AppError as exc:
        if exc.code != "artifact_not_found":
            raise
        return await get_source_video_artifact(
            session,
            source_video_id=source_video_id,
            role=SourceVideoArtifactRole.proxy_video,
        )
