from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from app.models.enums import UploadStatus
from app.schemas.common import AppSchema


class CreateUploadSessionRequest(BaseModel):
    filename: str
    content_type: str
    size_bytes: int
    sha256: str | None = None


class CompleteUploadSessionRequest(BaseModel):
    sha256: str
    size_bytes: int


class UploadSessionOut(AppSchema):
    id: UUID
    filename: str
    content_type: str
    declared_size_bytes: int
    declared_sha256: str | None
    storage_key: str
    status: UploadStatus
    expires_at: datetime
    completed_artifact_id: UUID | None
    upload_url: str | None = None
