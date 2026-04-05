from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.models.enums import IngestStatus, ProvenanceType, SourceType
from app.schemas.common import AppSchema


class SourceVideoProvenanceIn(BaseModel):
    provenance_type: ProvenanceType
    provider: str | None = None
    source_uri: str | None = None
    evidence_artifact_id: UUID | None = None
    approved_by: str | None = None
    approved_at: datetime | None = None


class CreateSourceVideoRequest(BaseModel):
    artifact_id: UUID | None = None
    approved_import_id: str | None = None
    brand_profile_id: UUID
    rights_attestation: bool = Field(default=False)
    source_type: SourceType
    duration_ms: int | None = None
    language: str | None = None
    speaker_count_estimate: int | None = None
    provenance: SourceVideoProvenanceIn | None = None


class SourceVideoOut(AppSchema):
    id: UUID
    brand_profile_id: UUID
    canonical_asset_id: UUID
    source_type: SourceType
    duration_ms: int | None
    language: str | None
    speaker_count_estimate: int | None
    rights_attestation: bool
    ingest_status: IngestStatus
