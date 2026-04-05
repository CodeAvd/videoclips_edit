import hashlib
import json
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.models.job import ApiIdempotencyKey


def fingerprint_payload(payload: dict) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


async def claim_idempotency_key(
    session: AsyncSession,
    *,
    endpoint_key: str,
    actor_ref: str,
    idempotency_key: str,
    request_payload: dict,
) -> tuple[ApiIdempotencyKey, bool]:
    request_fingerprint = fingerprint_payload(request_payload)
    result = await session.execute(
        select(ApiIdempotencyKey).where(
            ApiIdempotencyKey.endpoint_key == endpoint_key,
            ApiIdempotencyKey.actor_ref == actor_ref,
            ApiIdempotencyKey.idempotency_key == idempotency_key,
        )
    )
    record = result.scalars().first()
    if record is None:
        try:
            async with session.begin_nested():
                record = ApiIdempotencyKey(
                    endpoint_key=endpoint_key,
                    actor_ref=actor_ref,
                    idempotency_key=idempotency_key,
                    request_fingerprint=request_fingerprint,
                    status="in_progress",
                )
                session.add(record)
                await session.flush()
            return record, False
        except IntegrityError:
            result = await session.execute(
                select(ApiIdempotencyKey).where(
                    ApiIdempotencyKey.endpoint_key == endpoint_key,
                    ApiIdempotencyKey.actor_ref == actor_ref,
                    ApiIdempotencyKey.idempotency_key == idempotency_key,
                )
            )
            record = result.scalars().first()
            if record is None:
                raise

    if record.request_fingerprint != request_fingerprint:
        raise AppError(
            code="idempotency_conflict",
            message="The provided Idempotency-Key was already used with a different payload.",
            http_status=409,
        )
    if record.status == "completed" and record.response_jsonb is not None:
        return record, True
    raise AppError(
        code="idempotency_in_progress",
        message="An identical request with this Idempotency-Key is already in progress.",
        http_status=409,
        retryable=True,
    )


async def complete_idempotency_key(
    session: AsyncSession,
    *,
    record: ApiIdempotencyKey,
    response_status_code: int,
    response_payload: dict,
    resource_type: str | None = None,
    resource_id: str | None = None,
) -> None:
    record.status = "completed"
    record.response_status_code = response_status_code
    record.response_jsonb = response_payload
    record.resource_type = resource_type
    record.resource_id = resource_id
    record.completed_at = datetime.now(UTC)
    await session.flush()
