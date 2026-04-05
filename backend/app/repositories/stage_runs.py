from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.models.enums import StageName, StageRunStatus
from app.models.job import StageRun

LEASE_SECONDS = 300


def build_stage_run_query(job_id: UUID, stage_name: StageName, attempt_no: int) -> Select[tuple[StageRun]]:
    return (
        select(StageRun)
        .where(
            StageRun.job_id == job_id,
            StageRun.stage_name == stage_name,
            StageRun.attempt_no == attempt_no,
        )
        .with_for_update()
    )


async def get_stage_run(session: AsyncSession, job_id: UUID, stage_name: StageName, attempt_no: int) -> StageRun:
    result = await session.execute(build_stage_run_query(job_id, stage_name, attempt_no))
    stage_run = result.scalars().first()
    if stage_run is None:
        raise AppError(code="not_found", message="Stage run not found.", http_status=404)
    return stage_run


async def claim_stage_run(
    session: AsyncSession,
    *,
    job_id: UUID,
    stage_name: StageName,
    attempt_no: int,
    worker_id: str,
) -> StageRun:
    stage_run = await get_stage_run(session, job_id, stage_name, attempt_no)
    if stage_run.status not in {StageRunStatus.queued, StageRunStatus.claimed}:
        raise AppError(
            code="state_conflict",
            message=f"Stage run is not claimable from status {stage_run.status}.",
            http_status=409,
        )
    stage_run.status = StageRunStatus.running
    stage_run.worker_id = worker_id
    stage_run.lease_token = str(uuid4())
    stage_run.lease_expires_at = datetime.now(UTC) + timedelta(seconds=LEASE_SECONDS)
    stage_run.started_at = stage_run.started_at or datetime.now(UTC)
    await session.flush()
    return stage_run


async def succeed_stage_run(session: AsyncSession, stage_run: StageRun) -> None:
    stage_run.status = StageRunStatus.succeeded
    stage_run.ended_at = datetime.now(UTC)
    stage_run.lease_expires_at = None
    await session.flush()


async def block_stage_run(session: AsyncSession, stage_run: StageRun, *, error_code: str | None = None) -> None:
    stage_run.status = StageRunStatus.blocked_manual_review
    stage_run.error_code = error_code
    stage_run.ended_at = datetime.now(UTC)
    stage_run.lease_expires_at = None
    await session.flush()


async def fail_stage_run(
    session: AsyncSession,
    stage_run: StageRun,
    *,
    error_code: str,
    retryable: bool,
) -> None:
    stage_run.status = StageRunStatus.failed_retryable if retryable else StageRunStatus.failed_terminal
    stage_run.error_code = error_code
    stage_run.ended_at = datetime.now(UTC)
    stage_run.lease_expires_at = None
    await session.flush()
