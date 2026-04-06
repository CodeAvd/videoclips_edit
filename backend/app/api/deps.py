from typing import Annotated

from fastapi import Depends, Header
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.core.database import get_db_session
from app.core.security import AuthContext, get_auth_context, get_worker_auth_context
from app.services.storage import StorageService, get_storage_service

DbSession = Annotated[AsyncSession, Depends(get_db_session)]
Actor = Annotated[AuthContext, Depends(get_auth_context)]
WorkerActor = Annotated[AuthContext, Depends(get_worker_auth_context)]
Storage = Annotated[StorageService, Depends(get_storage_service)]


def require_idempotency_key(
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> str:
    if idempotency_key is None or not idempotency_key.strip():
        raise AppError(
            code="validation_error",
            message="Idempotency-Key header is required for this operation.",
            http_status=400,
        )
    return idempotency_key.strip()


IdempotencyKey = Annotated[str, Depends(require_idempotency_key)]
