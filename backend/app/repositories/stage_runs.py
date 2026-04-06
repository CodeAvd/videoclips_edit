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


def build_stage_run_id_query(stage_run_id: UUID) -> Select[tuple[StageRun]]:
    return select(StageRun).where(StageRun.id == stage_run_id).with_for_update()


async def get_stage_run(session: AsyncSession, job_id: UUID, stage_name: StageName, attempt_no: int) -> StageRun:
    result = await session.execute(build_stage_run_query(job_id, stage_name, attempt_no))
    stage_run = result.scalars().first()
    if stage_run is None:
        raise AppError(code="not_found", message="Stage run not found.", http_status=404)
    return stage_run


async def get_stage_run_by_id(session: AsyncSession, stage_run_id: UUID) -> StageRun:
    result = await session.execute(build_stage_run_id_query(stage_run_id))
    stage_run = result.scalars().first()
    if stage_run is None:
        raise AppError(code="not_found", message="Stage run not found.", http_status=404)
    return stage_run


def lease_deadline(*, now: datetime | None = None) -> datetime:
    current_time = now or datetime.now(UTC)
    return current_time + timedelta(seconds=LEASE_SECONDS)


def is_lease_expired(stage_run: StageRun, *, now: datetime | None = None) -> bool:
    if stage_run.lease_expires_at is None:
        return False
    current_time = now or datetime.now(UTC)
    lease_expires_at = stage_run.lease_expires_at
    if lease_expires_at.tzinfo is None:
        lease_expires_at = lease_expires_at.replace(tzinfo=UTC)
    return lease_expires_at <= current_time


async def claim_stage_run(
    session: AsyncSession,
    *,
    job_id: UUID,
    stage_name: StageName,
    attempt_no: int,
    worker_id: str,
) -> StageRun:
    stage_run = await get_stage_run(session, job_id, stage_name, attempt_no)
    now = datetime.now(UTC)
    if stage_run.status == StageRunStatus.queued:
        pass
    elif stage_run.status in {StageRunStatus.claimed, StageRunStatus.running} and is_lease_expired(stage_run, now=now):
        pass
    elif stage_run.status in {StageRunStatus.claimed, StageRunStatus.running}:
        raise AppError(
            code="lease_conflict",
            message=f"Stage run lease is still active for status {stage_run.status}.",
            http_status=409,
        )
    else:
        raise AppError(
            code="state_conflict",
            message=f"Stage run is not claimable from status {stage_run.status}.",
            http_status=409,
        )
    stage_run.status = StageRunStatus.running
    stage_run.worker_id = worker_id
    stage_run.lease_token = str(uuid4())
    stage_run.lease_expires_at = lease_deadline(now=now)
    stage_run.started_at = stage_run.started_at or now
    await session.flush()
    return stage_run


async def renew_stage_run_lease(
    session: AsyncSession,
    *,
    stage_run_id: UUID,
    lease_token: str,
) -> bool:
    stage_run = await get_stage_run_by_id(session, stage_run_id)
    if stage_run.status != StageRunStatus.running:
        return False
    if stage_run.lease_token != lease_token:
        return False
    stage_run.lease_expires_at = lease_deadline()
    await session.flush()
    return True


async def succeed_stage_run(session: AsyncSession, stage_run: StageRun) -> None:
    stage_run.status = StageRunStatus.succeeded
    stage_run.ended_at = datetime.now(UTC)
    stage_run.lease_token = None
    stage_run.lease_expires_at = None
    await session.flush()


async def block_stage_run(session: AsyncSession, stage_run: StageRun, *, error_code: str | None = None) -> None:
    stage_run.status = StageRunStatus.blocked_manual_review
    stage_run.error_code = error_code
    stage_run.ended_at = datetime.now(UTC)
    stage_run.lease_token = None
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
    stage_run.lease_token = None
    stage_run.lease_expires_at = None
    await session.flush()
