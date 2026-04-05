from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy import select

from app.api.deps import DbSession
from app.core.errors import AppError
from app.core.security import require_role
from app.models.enums import ActorRole
from app.models.job import Job, TranscriptRevision, TranscriptSegment, TranscriptWord
from app.schemas.common import ListResponse
from app.schemas.transcript import TranscriptSegmentOut, TranscriptWordOut

router = APIRouter()


async def get_current_transcript_revision_id(job_id: UUID, db: DbSession) -> UUID:
    job = await db.get(Job, job_id)
    if job is None:
        raise AppError(code="not_found", message="Job not found.", http_status=404)
    revision_id = await db.scalar(
        select(TranscriptRevision.id)
        .where(TranscriptRevision.job_id == job_id, TranscriptRevision.is_current.is_(True))
        .order_by(TranscriptRevision.version_no.desc())
        .limit(1)
    )
    if revision_id is None:
        raise AppError(code="not_found", message="Transcript revision not found.", http_status=404)
    return revision_id


@router.get(
    "/jobs/{job_id}/transcript-segments",
    response_model=ListResponse[TranscriptSegmentOut],
    dependencies=[Depends(require_role(ActorRole.viewer, ActorRole.reviewer, ActorRole.operator, ActorRole.admin))],
)
async def list_transcript_segments(job_id: UUID, db: DbSession) -> ListResponse[TranscriptSegmentOut]:
    revision_id = await get_current_transcript_revision_id(job_id, db)
    result = await db.execute(
        select(TranscriptSegment)
        .where(TranscriptSegment.transcript_revision_id == revision_id)
        .order_by(TranscriptSegment.seq_no.asc())
    )
    items = [TranscriptSegmentOut.model_validate(row) for row in result.scalars().all()]
    return ListResponse(items=items, next_cursor=None)


@router.get(
    "/jobs/{job_id}/transcript-words",
    response_model=ListResponse[TranscriptWordOut],
    dependencies=[Depends(require_role(ActorRole.viewer, ActorRole.reviewer, ActorRole.operator, ActorRole.admin))],
)
async def list_transcript_words(job_id: UUID, db: DbSession) -> ListResponse[TranscriptWordOut]:
    revision_id = await get_current_transcript_revision_id(job_id, db)
    result = await db.execute(
        select(TranscriptWord)
        .where(TranscriptWord.transcript_revision_id == revision_id)
        .order_by(TranscriptWord.seq_no.asc())
    )
    items = [TranscriptWordOut.model_validate(row) for row in result.scalars().all()]
    return ListResponse(items=items, next_cursor=None)
