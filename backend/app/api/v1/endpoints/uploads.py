from datetime import UTC, datetime
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy import select

from app.api.deps import Actor, DbSession, IdempotencyKey, Storage
from app.core.errors import AppError
from app.core.security import require_role
from app.models.enums import ActorRole, ArtifactKind, UploadStatus
from app.models.job import ArtifactObject, UploadSession
from app.services.idempotency import claim_idempotency_key, complete_idempotency_key
from app.services.storage import StorageError
from app.schemas.upload import CompleteUploadSessionRequest, CreateUploadSessionRequest, UploadSessionOut

router = APIRouter()


def serialize_upload_session(upload: UploadSession, *, upload_url: str | None) -> UploadSessionOut:
    return UploadSessionOut.model_validate(upload).model_copy(update={"upload_url": upload_url})


def upload_session_is_expired(upload: UploadSession) -> bool:
    expires_at = upload.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    return expires_at <= datetime.now(UTC)


@router.post("", response_model=UploadSessionOut, dependencies=[Depends(require_role(ActorRole.admin, ActorRole.operator))])
async def create_upload_session(payload: CreateUploadSessionRequest, db: DbSession, storage: Storage) -> UploadSessionOut:
    upload = UploadSession(
        filename=payload.filename,
        content_type=payload.content_type,
        declared_size_bytes=payload.size_bytes,
        declared_sha256=payload.sha256,
        storage_key=f"uploads/{uuid4()}/{payload.filename}",
        status=UploadStatus.created,
    )
    db.add(upload)
    await db.flush()
    await db.refresh(upload)
    return serialize_upload_session(
        upload,
        upload_url=storage.create_upload_url(upload_id=str(upload.id), storage_key=upload.storage_key),
    )


@router.put(
    "/{upload_id}/content",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_role(ActorRole.admin, ActorRole.operator))],
)
async def upload_content(
    upload_id: UUID,
    request: Request,
    db: DbSession,
    storage: Storage,
) -> Response:
    upload = await db.get(UploadSession, upload_id)
    if upload is None:
        raise AppError(code="not_found", message="Upload session not found.", http_status=404)
    if upload.status != UploadStatus.created:
        raise AppError(code="state_conflict", message="Upload session is not writable.", http_status=409)
    if upload_session_is_expired(upload):
        upload.status = UploadStatus.expired
        raise AppError(code="state_conflict", message="Upload session is expired.", http_status=409)
    if not storage.supports_direct_app_upload():
        raise AppError(code="unsupported_operation", message="Active storage backend does not support direct app uploads.", http_status=409)
    try:
        await storage.write_upload_stream(
            storage_key=upload.storage_key,
            content_type=upload.content_type,
            chunks=request.stream(),
        )
    except StorageError as exc:
        raise AppError(code="storage_error", message=str(exc), http_status=502) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{upload_id}/complete",
    response_model=UploadSessionOut,
    dependencies=[Depends(require_role(ActorRole.admin, ActorRole.operator))],
)
async def complete_upload_session(
    upload_id: UUID,
    payload: CompleteUploadSessionRequest,
    db: DbSession,
    storage: Storage,
    actor: Actor,
    idempotency_key: IdempotencyKey,
) -> UploadSessionOut:
    upload = await db.get(UploadSession, upload_id)
    if upload is None:
        raise AppError(code="not_found", message="Upload session not found.", http_status=404)

    idempotency_record, replayed = await claim_idempotency_key(
        db,
        endpoint_key="uploads.complete",
        actor_ref=actor.actor_id,
        idempotency_key=idempotency_key,
        request_payload={"upload_id": str(upload_id), **payload.model_dump(mode="json")},
    )
    if replayed:
        return UploadSessionOut.model_validate(idempotency_record.response_jsonb)

    if upload.status == UploadStatus.completed:
        response = serialize_upload_session(upload, upload_url=None)
        await complete_idempotency_key(
            db,
            record=idempotency_record,
            response_status_code=200,
            response_payload=response.model_dump(mode="json"),
            resource_type="upload_session",
            resource_id=str(upload.id),
        )
        return response
    if upload_session_is_expired(upload):
        upload.status = UploadStatus.expired
        raise AppError(code="state_conflict", message="Upload session is expired.", http_status=409)

    try:
        actual = storage.read_upload_metadata(storage_key=upload.storage_key)
    except StorageError as exc:
        raise AppError(code="storage_error", message=str(exc), http_status=422) from exc
    if actual.size_bytes != upload.declared_size_bytes:
        raise AppError(code="validation_error", message="Uploaded object size does not match declared upload size.", http_status=422)
    if upload.declared_sha256 is not None and actual.sha256 is not None and actual.sha256 != upload.declared_sha256:
        raise AppError(code="validation_error", message="Uploaded object checksum does not match declared upload checksum.", http_status=422)
    if actual.size_bytes != payload.size_bytes:
        raise AppError(code="validation_error", message="Uploaded object size does not match completion payload.", http_status=422)
    if actual.sha256 is not None and actual.sha256 != payload.sha256:
        raise AppError(code="validation_error", message="Uploaded object checksum does not match completion payload.", http_status=422)

    artifact = ArtifactObject(
        storage_key=upload.storage_key,
        kind=ArtifactKind.upload,
        sha256=actual.sha256 or payload.sha256,
        size_bytes=actual.size_bytes,
        mime_type=upload.content_type,
        metadata_jsonb={
            "filename": upload.filename,
            "completed_at": datetime.now(UTC).isoformat(),
            "storage_backend": actual.backend,
        },
    )
    db.add(artifact)
    await db.flush()
    upload.completed_artifact_id = artifact.id
    upload.status = UploadStatus.completed
    await db.flush()
    await db.refresh(upload)
    response = serialize_upload_session(upload, upload_url=None)
    await complete_idempotency_key(
        db,
        record=idempotency_record,
        response_status_code=200,
        response_payload=response.model_dump(mode="json"),
        resource_type="upload_session",
        resource_id=str(upload.id),
    )
    return response


@router.get(
    "/{upload_id}",
    response_model=UploadSessionOut,
    dependencies=[Depends(require_role(ActorRole.admin, ActorRole.operator, ActorRole.reviewer, ActorRole.viewer))],
)
async def get_upload_session(upload_id: UUID, db: DbSession, storage: Storage) -> UploadSessionOut:
    upload = await db.get(UploadSession, upload_id)
    if upload is None:
        raise AppError(code="not_found", message="Upload session not found.", http_status=404)
    upload_url = None
    if upload.status == UploadStatus.created:
        upload_url = storage.create_upload_url(upload_id=str(upload.id), storage_key=upload.storage_key)
    return serialize_upload_session(upload, upload_url=upload_url)
