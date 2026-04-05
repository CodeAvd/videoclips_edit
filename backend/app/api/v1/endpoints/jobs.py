import hashlib
import json
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy import and_, desc, select

from app.api.deps import Actor, DbSession, IdempotencyKey
from app.core.errors import AppError
from app.core.security import require_role
from app.models.job import Job, JobConfigSnapshot, JobTargetPlatform, SourceVideo, StageRun
from app.models.enums import ActorRole, IngestStatus, JobStatus, StageName
from app.services.idempotency import claim_idempotency_key, complete_idempotency_key
from app.services.orchestration import enqueue_stage, transition_job_status
from app.schemas.common import ListResponse
from app.schemas.job import CreateJobRequest, JobAcceptedOut, JobOut, ResolveIntakeReviewRequest, StageRunOut

router = APIRouter()


def build_job_checksum(payload: CreateJobRequest) -> str:
    canonical_payload = payload.model_dump(mode="json")
    canonical_payload["target_platforms"] = sorted(canonical_payload["target_platforms"])
    raw = json.dumps(canonical_payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


@router.post("", response_model=JobAcceptedOut, dependencies=[Depends(require_role(ActorRole.operator, ActorRole.admin))])
async def create_job(payload: CreateJobRequest, db: DbSession, actor: Actor, idempotency_key: IdempotencyKey) -> JobAcceptedOut:
    if payload.publish_mode != "approval_gated":
        raise AppError(code="validation_error", message="Only approval_gated publish mode is supported in v1.", http_status=422)

    source_video = await db.get(SourceVideo, payload.source_video_id)
    if source_video is None:
        raise AppError(code="not_found", message="Source video not found.", http_status=404)

    idempotency_record, replayed = await claim_idempotency_key(
        db,
        endpoint_key="jobs.create",
        actor_ref=actor.actor_id,
        idempotency_key=idempotency_key,
        request_payload=payload.model_dump(mode="json"),
    )
    if replayed:
        return JobAcceptedOut.model_validate(idempotency_record.response_jsonb)

    checksum = build_job_checksum(payload)
    existing_query = (
        select(Job, JobConfigSnapshot)
        .join(JobConfigSnapshot, JobConfigSnapshot.job_id == Job.id)
        .where(
            and_(
                Job.source_video_id == payload.source_video_id,
                JobConfigSnapshot.checksum == checksum,
                JobConfigSnapshot.is_current.is_(True),
            )
        )
        .order_by(desc(Job.created_at))
        .limit(1)
    )
    existing = (await db.execute(existing_query)).first()
    if existing is not None:
        job, snapshot = existing
        response = JobAcceptedOut(job_id=job.id, status=job.status, current_job_config_snapshot_id=snapshot.id)
        await complete_idempotency_key(
            db,
            record=idempotency_record,
            response_status_code=200,
            response_payload=response.model_dump(mode="json"),
            resource_type="job",
            resource_id=str(job.id),
        )
        return response

    job = Job(
        source_video_id=source_video.id,
        brand_profile_id=source_video.brand_profile_id,
        target_final_clip_count=payload.target_final_clip_count,
        status=JobStatus.created,
        prompt_version=payload.prompt_version,
        scoring_policy_version=payload.scoring_policy_version,
        version=1,
    )
    db.add(job)
    await db.flush()

    for platform in payload.target_platforms:
        db.add(JobTargetPlatform(job_id=job.id, platform=platform))

    snapshot = JobConfigSnapshot(
        job_id=job.id,
        version_no=1,
        is_current=True,
        checksum=checksum,
        target_final_clip_count=payload.target_final_clip_count,
        shortlist_target_count=payload.shortlist_target_count,
        prompt_version=payload.prompt_version,
        scoring_policy_version=payload.scoring_policy_version,
        config_jsonb=payload.model_dump(mode="json"),
    )
    db.add(snapshot)
    await db.flush()

    stage_run = await enqueue_stage(
        db,
        job_id=job.id,
        stage_name=StageName.intake,
        dedupe_key=f"job:{job.id}:stage:{StageName.intake.value}:attempt:1",
    )
    await transition_job_status(
        db,
        job=job,
        to_status=JobStatus.created,
        stage_run_id=stage_run.id,
        actor_type="user",
        actor_ref=actor.actor_id,
        reason_code="job_created",
    )
    response = JobAcceptedOut(job_id=job.id, status=job.status, current_job_config_snapshot_id=snapshot.id)
    await complete_idempotency_key(
        db,
        record=idempotency_record,
        response_status_code=200,
        response_payload=response.model_dump(mode="json"),
        resource_type="job",
        resource_id=str(job.id),
    )
    return response


@router.get("", response_model=ListResponse[JobOut], dependencies=[Depends(require_role(ActorRole.viewer, ActorRole.reviewer, ActorRole.operator, ActorRole.admin))])
async def list_jobs(db: DbSession) -> ListResponse[JobOut]:
    result = await db.execute(select(Job).order_by(Job.created_at.desc()))
    items = [JobOut.model_validate(job) for job in result.scalars().all()]
    return ListResponse(items=items, next_cursor=None)


@router.get(
    "/{job_id}",
    response_model=JobOut,
    dependencies=[Depends(require_role(ActorRole.viewer, ActorRole.reviewer, ActorRole.operator, ActorRole.admin))],
)
async def get_job(job_id: UUID, db: DbSession) -> JobOut:
    job = await db.get(Job, job_id)
    if job is None:
        raise AppError(code="not_found", message="Job not found.", http_status=404)
    return JobOut.model_validate(job)


@router.get(
    "/{job_id}/stage-runs",
    response_model=ListResponse[StageRunOut],
    dependencies=[Depends(require_role(ActorRole.viewer, ActorRole.reviewer, ActorRole.operator, ActorRole.admin))],
)
async def list_stage_runs(job_id: UUID, db: DbSession) -> ListResponse[StageRunOut]:
    result = await db.execute(
        select(StageRun).where(StageRun.job_id == job_id).order_by(StageRun.created_at.desc())
    )
    items = [StageRunOut.model_validate(run) for run in result.scalars().all()]
    return ListResponse(items=items, next_cursor=None)


@router.post(
    "/{job_id}/actions/resolve-intake-review",
    response_model=JobOut,
    dependencies=[Depends(require_role(ActorRole.reviewer, ActorRole.operator, ActorRole.admin))],
)
async def resolve_intake_review(
    job_id: UUID,
    payload: ResolveIntakeReviewRequest,
    db: DbSession,
    actor: Actor,
    idempotency_key: IdempotencyKey,
) -> JobOut:
    job = await db.get(Job, job_id)
    if job is None:
        raise AppError(code="not_found", message="Job not found.", http_status=404)
    idempotency_record, replayed = await claim_idempotency_key(
        db,
        endpoint_key="jobs.resolve_intake_review",
        actor_ref=actor.actor_id,
        idempotency_key=idempotency_key,
        request_payload={"job_id": str(job_id), **payload.model_dump(mode="json")},
    )
    if replayed:
        return JobOut.model_validate(idempotency_record.response_jsonb)
    if job.status != JobStatus.awaiting_manual_review:
        raise AppError(code="state_conflict", message="Job is not awaiting manual review.", http_status=409)
    source_video = await db.get(SourceVideo, job.source_video_id)
    if payload.decision == "cancel":
        await transition_job_status(
            db,
            job=job,
            to_status=JobStatus.cancelled,
            stage_run_id=None,
            actor_type="user",
            actor_ref=actor.actor_id,
            reason_code=payload.reason_code or "manual_review_cancelled",
        )
        response = JobOut.model_validate(job)
        await complete_idempotency_key(
            db,
            record=idempotency_record,
            response_status_code=200,
            response_payload=response.model_dump(mode="json"),
            resource_type="job",
            resource_id=str(job.id),
        )
        return response
    if payload.decision != "approve":
        raise AppError(code="validation_error", message="Decision must be approve or cancel.", http_status=422)
    source_video.ingest_status = IngestStatus.accepted
    await transition_job_status(
        db,
        job=job,
        to_status=JobStatus.processing,
        stage_run_id=None,
        actor_type="user",
        actor_ref=actor.actor_id,
        reason_code=payload.reason_code or "manual_review_approved",
    )
    await enqueue_stage(
        db,
        job_id=job.id,
        stage_name=StageName.ingest,
        dedupe_key=f"job:{job.id}:stage:{StageName.ingest.value}:manual-resume",
    )
    response = JobOut.model_validate(job)
    await complete_idempotency_key(
        db,
        record=idempotency_record,
        response_status_code=200,
        response_payload=response.model_dump(mode="json"),
        resource_type="job",
        resource_id=str(job.id),
    )
    return response
