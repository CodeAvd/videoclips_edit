from datetime import UTC, datetime
from uuid import UUID

import pytest
from sqlalchemy import select

from app.core.errors import AppError
from app.models.enums import JobStatus, OutboxStatus, StageRunStatus
from app.models.job import Job, OutboxEvent, StageRun
from app.services import worker_runtime
from flow_helpers import create_job, create_uploaded_source_video


def ensure_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value

async def test_process_next_outbox_event_requeues_retryable_failures(client, actor_headers, session_factory, monkeypatch) -> None:
    _, source_video_id = await create_uploaded_source_video(client, actor_headers)
    job_payload = await create_job(client, actor_headers, source_video_id)
    job_id = UUID(job_payload["job_id"])

    async def fail_dispatch(*_args, **_kwargs):
        raise RuntimeError("temporary-storage-failure")

    monkeypatch.setattr(worker_runtime, "SessionLocal", session_factory)
    monkeypatch.setattr(worker_runtime, "dispatch_outbox_event", fail_dispatch)

    with pytest.raises(RuntimeError):
        await worker_runtime.process_next_outbox_event(worker_id="retry-worker")

    async with session_factory() as session:
        events = (
            await session.execute(
                select(OutboxEvent).where(OutboxEvent.aggregate_id == job_payload["job_id"]).order_by(OutboxEvent.created_at.asc())
            )
        ).scalars().all()
        assert len(events) == 2

        failed_event, retry_event = events
        assert failed_event.status == OutboxStatus.failed
        assert failed_event.retry_count == 1
        assert failed_event.last_error_code == "RuntimeError"

        assert retry_event.status == OutboxStatus.pending
        assert retry_event.retry_count == 1
        assert retry_event.payload_jsonb["attempt_no"] == 2
        assert ensure_aware(retry_event.available_at) > datetime.now(UTC)

        stage_runs = (
            await session.execute(select(StageRun).where(StageRun.job_id == job_id).order_by(StageRun.attempt_no.asc()))
        ).scalars().all()
        assert len(stage_runs) == 2
        assert stage_runs[0].attempt_no == 1
        assert stage_runs[0].status == StageRunStatus.failed_retryable
        assert stage_runs[0].error_code == "RuntimeError"
        assert stage_runs[1].attempt_no == 2
        assert stage_runs[1].status == StageRunStatus.queued


async def test_process_next_outbox_event_marks_terminal_failures(client, actor_headers, session_factory, monkeypatch) -> None:
    _, source_video_id = await create_uploaded_source_video(client, actor_headers)
    job_payload = await create_job(client, actor_headers, source_video_id)
    job_id = UUID(job_payload["job_id"])

    async def fail_dispatch(*_args, **_kwargs):
        raise AppError(code="terminal_failure", message="bad input", http_status=422)

    monkeypatch.setattr(worker_runtime, "SessionLocal", session_factory)
    monkeypatch.setattr(worker_runtime, "dispatch_outbox_event", fail_dispatch)

    with pytest.raises(AppError):
        await worker_runtime.process_next_outbox_event(worker_id="terminal-worker")

    async with session_factory() as session:
        events = (
            await session.execute(
                select(OutboxEvent).where(OutboxEvent.aggregate_id == job_payload["job_id"])
            )
        ).scalars().all()
        assert len(events) == 1
        event = events[0]
        assert event.status == OutboxStatus.failed
        assert event.retry_count == 1
        assert event.last_error_code == "terminal_failure"

        stage_run = (
            await session.execute(select(StageRun).where(StageRun.job_id == job_id))
        ).scalars().one()
        assert stage_run.status == StageRunStatus.failed_terminal
        assert stage_run.error_code == "terminal_failure"

        job = await session.get(Job, job_id)
        assert job is not None
        assert job.status == JobStatus.failed
