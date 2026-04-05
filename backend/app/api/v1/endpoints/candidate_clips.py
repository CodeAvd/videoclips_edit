from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select

from app.api.deps import DbSession
from app.core.errors import AppError
from app.core.security import require_role
from app.models.enums import ActorRole
from app.models.job import CandidateClip, CandidateSet, Job
from app.schemas.candidate import CandidateClipOut
from app.schemas.common import ListResponse

router = APIRouter()


async def get_current_candidate_set_id(job_id: UUID, db: DbSession) -> UUID:
    job = await db.get(Job, job_id)
    if job is None:
        raise AppError(code="not_found", message="Job not found.", http_status=404)
    candidate_set_id = await db.scalar(
        select(CandidateSet.id)
        .where(CandidateSet.job_id == job_id, CandidateSet.is_current.is_(True))
        .order_by(CandidateSet.version_no.desc())
        .limit(1)
    )
    if candidate_set_id is None:
        raise AppError(code="not_found", message="Candidate set not found.", http_status=404)
    return candidate_set_id


@router.get(
    "/jobs/{job_id}/candidate-clips",
    response_model=ListResponse[CandidateClipOut],
    dependencies=[Depends(require_role(ActorRole.viewer, ActorRole.reviewer, ActorRole.operator, ActorRole.admin))],
)
async def list_candidate_clips(
    job_id: UUID,
    db: DbSession,
    length_bucket: str | None = Query(default=None),
    topic_cluster: str | None = Query(default=None),
    duplicate_group: str | None = Query(default=None),
) -> ListResponse[CandidateClipOut]:
    candidate_set_id = await get_current_candidate_set_id(job_id, db)
    query = select(CandidateClip).where(CandidateClip.candidate_set_id == candidate_set_id)
    if length_bucket:
        query = query.where(CandidateClip.length_bucket == length_bucket)
    if topic_cluster:
        query = query.where(CandidateClip.topic_cluster == topic_cluster)
    if duplicate_group:
        query = query.where(CandidateClip.duplicate_group == duplicate_group)
    result = await db.execute(query.order_by(CandidateClip.rank_no.asc()))
    items = [CandidateClipOut.model_validate(candidate) for candidate in result.scalars().all()]
    return ListResponse(items=items, next_cursor=None)


@router.get(
    "/candidate-clips/{candidate_clip_id}",
    response_model=CandidateClipOut,
    dependencies=[Depends(require_role(ActorRole.viewer, ActorRole.reviewer, ActorRole.operator, ActorRole.admin))],
)
async def get_candidate_clip(candidate_clip_id: UUID, db: DbSession) -> CandidateClipOut:
    candidate = await db.get(CandidateClip, candidate_clip_id)
    if candidate is None:
        raise AppError(code="not_found", message="Candidate clip not found.", http_status=404)
    return CandidateClipOut.model_validate(candidate)
