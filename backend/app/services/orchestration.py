from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.enums import JobStatus, OutboxStatus, StageName, StageRunStatus
from app.models.job import Job, JobStatusTransition, OutboxEvent, StageRun

settings = get_settings()


async def transition_job_status(
    session: AsyncSession,
    *,
    job: Job,
    to_status: JobStatus,
    stage_run_id: UUID | None,
    actor_type: str,
    actor_ref: str | None,
    reason_code: str,
) -> None:
    from_status = job.status
    if from_status != to_status:
        job.status = to_status
        job.version += 1
    session.add(
        JobStatusTransition(
            job_id=job.id,
            from_status=from_status,
            to_status=to_status,
            stage_run_id=stage_run_id,
            actor_type=actor_type,
            actor_ref=actor_ref,
            reason_code=reason_code,
        )
    )
    await session.flush()


async def next_stage_attempt_no(session: AsyncSession, *, job_id: UUID, stage_name: StageName) -> int:
    stmt = select(func.max(StageRun.attempt_no)).where(StageRun.job_id == job_id, StageRun.stage_name == stage_name)
    current_max = await session.scalar(stmt)
    return int(current_max or 0) + 1


async def enqueue_stage(
    session: AsyncSession,
    *,
    job_id: UUID,
    stage_name: StageName,
    dedupe_key: str,
) -> StageRun:
    attempt_no = await next_stage_attempt_no(session, job_id=job_id, stage_name=stage_name)
    stage_run = StageRun(
        job_id=job_id,
        stage_name=stage_name,
        attempt_no=attempt_no,
        status=StageRunStatus.queued,
    )
    session.add(stage_run)
    await session.flush()
    session.add(
        OutboxEvent(
            aggregate_type="job",
            aggregate_id=str(job_id),
            event_type=f"stage.{stage_name.value}.queued",
            dedupe_key=dedupe_key,
            payload_jsonb={
                "job_id": str(job_id),
                "stage_name": stage_name.value,
                "attempt_no": attempt_no,
                "stage_run_id": str(stage_run.id),
            },
            status=OutboxStatus.pending,
            available_at=datetime.now(UTC),
            max_retries=settings.outbox_max_retries,
        )
    )
    await session.flush()
    return stage_run
