from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy import select

from app.api.deps import DbSession
from app.core.errors import AppError
from app.core.security import require_role
from app.models.config import BrandProfile
from app.models.enums import ActorRole, ArtifactKind, IngestStatus, SourceType
from app.models.job import ArtifactObject, SourceVideo, SourceVideoArtifact, SourceVideoProvenance
from app.schemas.source_video import CreateSourceVideoRequest, SourceVideoOut

router = APIRouter()


@router.post("", response_model=SourceVideoOut, dependencies=[Depends(require_role(ActorRole.operator, ActorRole.admin))])
async def create_source_video(payload: CreateSourceVideoRequest, db: DbSession) -> SourceVideoOut:
    brand = await db.get(BrandProfile, payload.brand_profile_id)
    if brand is None:
        raise AppError(code="not_found", message="Brand profile not found.", http_status=404)
    if not payload.rights_attestation:
        raise AppError(code="validation_error", message="rights_attestation must be true.", http_status=422)
    if payload.source_type == SourceType.uploaded_asset and payload.artifact_id is None:
        raise AppError(code="validation_error", message="artifact_id is required for uploaded assets.", http_status=422)
    if payload.source_type == SourceType.approved_import and not payload.approved_import_id:
        raise AppError(code="validation_error", message="approved_import_id is required for approved imports.", http_status=422)
    if payload.source_type == SourceType.approved_import and payload.provenance is None:
        raise AppError(code="validation_error", message="provenance is required for approved imports.", http_status=422)

    if payload.artifact_id is not None:
        artifact = await db.get(ArtifactObject, payload.artifact_id)
        if artifact is None:
            raise AppError(code="not_found", message="Artifact not found.", http_status=404)
        if payload.source_type == SourceType.uploaded_asset and artifact.kind != ArtifactKind.upload:
            raise AppError(code="validation_error", message="uploaded_asset sources must reference an upload artifact.", http_status=422)
        canonical_asset_id = artifact.id
    else:
        artifact = ArtifactObject(
            storage_key=f"imports/{payload.approved_import_id}",
            kind=ArtifactKind.source_video,
            sha256=payload.approved_import_id or "approved-import",
            size_bytes=0,
            mime_type="video/mp4",
            metadata_jsonb={"approved_import_id": payload.approved_import_id},
        )
        db.add(artifact)
        await db.flush()
        canonical_asset_id = artifact.id

    source_video = SourceVideo(
        brand_profile_id=payload.brand_profile_id,
        canonical_asset_id=canonical_asset_id,
        source_type=payload.source_type,
        duration_ms=payload.duration_ms,
        language=payload.language,
        speaker_count_estimate=payload.speaker_count_estimate,
        rights_attestation=payload.rights_attestation,
        ingest_status=IngestStatus.pending,
    )
    db.add(source_video)
    await db.flush()
    db.add(SourceVideoArtifact(source_video_id=source_video.id, artifact_id=canonical_asset_id, role="source_asset"))

    if payload.provenance is not None:
        provenance = SourceVideoProvenance(source_video_id=source_video.id, **payload.provenance.model_dump())
        db.add(provenance)

    await db.flush()
    await db.refresh(source_video)
    return SourceVideoOut.model_validate(source_video)


@router.get(
    "/{source_video_id}",
    response_model=SourceVideoOut,
    dependencies=[Depends(require_role(ActorRole.viewer, ActorRole.reviewer, ActorRole.operator, ActorRole.admin))],
)
async def get_source_video(source_video_id: UUID, db: DbSession) -> SourceVideoOut:
    source_video = await db.get(SourceVideo, source_video_id)
    if source_video is None:
        raise AppError(code="not_found", message="Source video not found.", http_status=404)
    return SourceVideoOut.model_validate(source_video)
