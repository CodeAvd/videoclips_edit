from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import Select, and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.enums import OutboxStatus
from app.models.job import OutboxEvent

settings = get_settings()


def build_pending_outbox_query() -> Select[tuple[OutboxEvent]]:
    now = datetime.now(UTC)
    return (
        select(OutboxEvent)
        .where(
            or_(
                and_(
                    OutboxEvent.status == OutboxStatus.pending,
                    OutboxEvent.available_at <= now,
                ),
                and_(
                    OutboxEvent.status == OutboxStatus.claimed,
                    OutboxEvent.lease_expires_at.is_not(None),
                    OutboxEvent.lease_expires_at <= now,
                ),
            ),
        )
        .order_by(OutboxEvent.created_at.asc())
        .with_for_update(skip_locked=True)
    )


async def claim_next_outbox_event(session: AsyncSession) -> OutboxEvent | None:
    result = await session.execute(build_pending_outbox_query())
    event = result.scalars().first()
    if event is None:
        return None
    now = datetime.now(UTC)
    event.status = OutboxStatus.claimed
    event.claimed_at = now
    event.lease_expires_at = now + timedelta(seconds=settings.outbox_claim_ttl_seconds)
    await session.flush()
    return event


async def mark_outbox_processed(session: AsyncSession, event: OutboxEvent) -> None:
    event.status = OutboxStatus.processed
    event.processed_at = datetime.now(UTC)
    event.lease_expires_at = None
    await session.flush()


def compute_backoff_seconds(retry_count: int) -> int:
    return min(settings.outbox_retry_max_seconds, settings.outbox_retry_base_seconds * (2 ** max(retry_count - 1, 0)))


async def mark_outbox_failed(
    session: AsyncSession,
    event: OutboxEvent,
    *,
    error_code: str,
    error_message: str,
    retryable: bool,
) -> None:
    now = datetime.now(UTC)
    next_retry_count = event.retry_count + 1
    event.retry_count = next_retry_count
    event.last_error_code = error_code
    event.last_error_message = error_message[:1000]
    event.last_error_at = now
    event.claimed_at = None
    event.lease_expires_at = None
    if retryable and next_retry_count <= event.max_retries:
        event.status = OutboxStatus.pending
        event.available_at = now + timedelta(seconds=compute_backoff_seconds(next_retry_count))
    else:
        event.status = OutboxStatus.failed
    await session.flush()


async def get_outbox_event(session: AsyncSession, event_id: UUID) -> OutboxEvent | None:
    return await session.get(OutboxEvent, event_id)
