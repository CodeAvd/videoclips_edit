from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select

from app.models.enums import OutboxStatus, StageRunStatus
from app.models.job import OutboxEvent, StageRun
from app.repositories.outbox import claim_next_outbox_event
from app.repositories.stage_runs import claim_stage_run, succeed_stage_run
from app.services import worker_runtime
from flow_helpers import create_job, create_uploaded_source_video


def ensure_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


async def test_claim_stage_run_reclaims_expired_running_lease(client, actor_headers, session_factory) -> None:
    _, source_video_id = await create_uploaded_source_video(client, actor_headers)
    job_payload = await create_job(client, actor_headers, source_video_id)
    job_id = UUID(job_payload["job_id"])
    original_started_at = datetime.now(UTC) - timedelta(minutes=5)

    async with session_factory() as session:
        stage_run = (await session.execute(select(StageRun).where(StageRun.job_id == job_id))).scalars().one()
        stage_run.status = StageRunStatus.running
        stage_run.worker_id = "stale-worker"
        stage_run.lease_token = "expired-token"
        stage_run.started_at = original_started_at
        stage_run.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
        await session.commit()

    async with session_factory() as session:
        reclaimed = await claim_stage_run(
            session,
            job_id=job_id,
            stage_name=stage_run.stage_name,
            attempt_no=stage_run.attempt_no,
            worker_id="new-worker",
        )
        assert reclaimed.status == StageRunStatus.running
        assert reclaimed.worker_id == "new-worker"
        assert reclaimed.lease_token != "expired-token"
        assert ensure_aware(reclaimed.started_at) == original_started_at
        assert ensure_aware(reclaimed.lease_expires_at) > datetime.now(UTC)


async def test_renew_claimed_execution_leases_extends_stage_and_outbox_deadlines(
    client,
    actor_headers,
    session_factory,
    monkeypatch,
) -> None:
    _, source_video_id = await create_uploaded_source_video(client, actor_headers)
    job_payload = await create_job(client, actor_headers, source_video_id)
    job_id = UUID(job_payload["job_id"])
    worker_id = "heartbeat-worker"

    async with session_factory() as session:
        event = await claim_next_outbox_event(session)
        assert event is not None
        current_job_id, stage_name, attempt_no = worker_runtime.parse_event_payload(event.payload_jsonb)
        assert current_job_id == job_id
        stage_run = await claim_stage_run(
            session,
            job_id=current_job_id,
            stage_name=stage_name,
            attempt_no=attempt_no,
            worker_id=worker_id,
        )
        await session.commit()
        outbox_before = ensure_aware(event.lease_expires_at)
        stage_before = ensure_aware(stage_run.lease_expires_at)

    monkeypatch.setattr(worker_runtime, "SessionLocal", session_factory)
    await worker_runtime.renew_claimed_execution_leases(
        event_id=event.id,
        job_id=job_id,
        stage_name=stage_run.stage_name,
        attempt_no=stage_run.attempt_no,
        worker_id=worker_id,
    )

    async with session_factory() as session:
        event = (await session.execute(select(OutboxEvent).where(OutboxEvent.aggregate_id == job_payload["job_id"]))).scalars().one()
        stage_run = (await session.execute(select(StageRun).where(StageRun.job_id == job_id))).scalars().one()
        assert ensure_aware(event.lease_expires_at) > outbox_before
        assert ensure_aware(stage_run.lease_expires_at) > stage_before
        await succeed_stage_run(session, stage_run)
        await session.commit()

    async with session_factory() as session:
        event = (await session.execute(select(OutboxEvent).where(OutboxEvent.aggregate_id == job_payload["job_id"]))).scalars().one()
        stage_run = (await session.execute(select(StageRun).where(StageRun.job_id == job_id))).scalars().one()
        assert event.status == OutboxStatus.claimed
        assert stage_run.status == StageRunStatus.succeeded
