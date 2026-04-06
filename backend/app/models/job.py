from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import (
    BigInteger,
    DateTime,
    Enum,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import BaseModel, CreatedAtMixin, UpdatedAtMixin, UuidPrimaryKeyMixin
from app.models.enums import (
    ArtifactKind,
    CandidateLabelValue,
    EvalSetStatus,
    IngestStatus,
    JobStatus,
    OutboxStatus,
    Platform,
    ProvenanceType,
    SourceType,
    StageName,
    StageRunStatus,
    UploadStatus,
)


def default_upload_expiry() -> datetime:
    return datetime.now(UTC) + timedelta(hours=24)


class UploadSession(UuidPrimaryKeyMixin, CreatedAtMixin, BaseModel):
    __tablename__ = "upload_session"

    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(255), nullable=False)
    declared_size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    declared_sha256: Mapped[str | None] = mapped_column(String(128))
    storage_key: Mapped[str] = mapped_column(String(512), nullable=False, unique=True)
    status: Mapped[UploadStatus] = mapped_column(Enum(UploadStatus, native_enum=False), nullable=False, default=UploadStatus.created)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=default_upload_expiry)
    completed_artifact_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("artifact_object.id"))


class ArtifactObject(UuidPrimaryKeyMixin, CreatedAtMixin, BaseModel):
    __tablename__ = "artifact_object"

    storage_key: Mapped[str] = mapped_column(String(512), nullable=False, unique=True)
    kind: Mapped[ArtifactKind] = mapped_column(Enum(ArtifactKind, native_enum=False), nullable=False)
    sha256: Mapped[str] = mapped_column(String(128), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    mime_type: Mapped[str] = mapped_column(String(255), nullable=False)
    metadata_jsonb: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)


class SourceVideo(UuidPrimaryKeyMixin, CreatedAtMixin, UpdatedAtMixin, BaseModel):
    __tablename__ = "source_video"

    brand_profile_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("brand_profile.id"), nullable=False)
    canonical_asset_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("artifact_object.id"), nullable=False)
    source_type: Mapped[SourceType] = mapped_column(Enum(SourceType, native_enum=False), nullable=False)
    duration_ms: Mapped[int | None] = mapped_column(BigInteger)
    language: Mapped[str | None] = mapped_column(String(32))
    speaker_count_estimate: Mapped[int | None] = mapped_column(Integer)
    rights_attestation: Mapped[bool] = mapped_column(nullable=False, default=False)
    ingest_status: Mapped[IngestStatus] = mapped_column(Enum(IngestStatus, native_enum=False), nullable=False, default=IngestStatus.pending)


class SourceVideoProvenance(UuidPrimaryKeyMixin, CreatedAtMixin, BaseModel):
    __tablename__ = "source_video_provenance"

    source_video_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("source_video.id"), nullable=False)
    provenance_type: Mapped[ProvenanceType] = mapped_column(Enum(ProvenanceType, native_enum=False), nullable=False)
    provider: Mapped[str | None] = mapped_column(String(255))
    source_uri: Mapped[str | None] = mapped_column(Text)
    evidence_artifact_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("artifact_object.id"))
    approved_by: Mapped[str | None] = mapped_column(String(255))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class SourceVideoArtifact(CreatedAtMixin, BaseModel):
    __tablename__ = "source_video_artifact"

    source_video_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("source_video.id"), primary_key=True)
    artifact_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("artifact_object.id"), primary_key=True)
    role: Mapped[str] = mapped_column(String(64), primary_key=True)


class Job(UuidPrimaryKeyMixin, CreatedAtMixin, UpdatedAtMixin, BaseModel):
    __tablename__ = "job"

    source_video_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("source_video.id"), nullable=False)
    brand_profile_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("brand_profile.id"), nullable=False)
    target_final_clip_count: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[JobStatus] = mapped_column(Enum(JobStatus, native_enum=False), nullable=False, default=JobStatus.created)
    prompt_version: Mapped[str] = mapped_column(String(128), nullable=False)
    scoring_policy_version: Mapped[str] = mapped_column(String(128), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)


class JobTargetPlatform(CreatedAtMixin, BaseModel):
    __tablename__ = "job_target_platform"

    job_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("job.id"), primary_key=True)
    platform: Mapped[Platform] = mapped_column(Enum(Platform, native_enum=False), primary_key=True)


class JobConfigSnapshot(UuidPrimaryKeyMixin, CreatedAtMixin, BaseModel):
    __tablename__ = "job_config_snapshot"
    __table_args__ = (UniqueConstraint("job_id", "version_no", name="uq_job_config_snapshot_job_version"),)

    job_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("job.id"), nullable=False)
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    is_current: Mapped[bool] = mapped_column(nullable=False, default=True)
    checksum: Mapped[str] = mapped_column(String(128), nullable=False)
    target_final_clip_count: Mapped[int] = mapped_column(Integer, nullable=False)
    shortlist_target_count: Mapped[int] = mapped_column(Integer, nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(128), nullable=False)
    scoring_policy_version: Mapped[str] = mapped_column(String(128), nullable=False)
    config_jsonb: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)


class StageRun(UuidPrimaryKeyMixin, CreatedAtMixin, BaseModel):
    __tablename__ = "stage_run"
    __table_args__ = (
        UniqueConstraint("job_id", "stage_name", "attempt_no", name="uq_stage_run_job_stage_attempt"),
    )

    job_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("job.id"), nullable=False)
    stage_name: Mapped[StageName] = mapped_column(Enum(StageName, native_enum=False), nullable=False)
    attempt_no: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[StageRunStatus] = mapped_column(Enum(StageRunStatus, native_enum=False), nullable=False)
    worker_id: Mapped[str | None] = mapped_column(String(255))
    lease_token: Mapped[str | None] = mapped_column(String(255))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(255))
    cost_usd: Mapped[float | None] = mapped_column(Numeric(12, 4))


class JobStatusTransition(UuidPrimaryKeyMixin, CreatedAtMixin, BaseModel):
    __tablename__ = "job_status_transition"

    job_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("job.id"), nullable=False)
    from_status: Mapped[JobStatus | None] = mapped_column(Enum(JobStatus, native_enum=False))
    to_status: Mapped[JobStatus] = mapped_column(Enum(JobStatus, native_enum=False), nullable=False)
    stage_run_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("stage_run.id"))
    actor_type: Mapped[str | None] = mapped_column(String(64))
    actor_ref: Mapped[str | None] = mapped_column(String(255))
    reason_code: Mapped[str | None] = mapped_column(String(255))


class OutboxEvent(UuidPrimaryKeyMixin, CreatedAtMixin, BaseModel):
    __tablename__ = "outbox_event"

    aggregate_type: Mapped[str] = mapped_column(String(128), nullable=False)
    aggregate_id: Mapped[str] = mapped_column(String(255), nullable=False)
    event_type: Mapped[str] = mapped_column(String(255), nullable=False)
    dedupe_key: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    payload_jsonb: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    status: Mapped[OutboxStatus] = mapped_column(Enum(OutboxStatus, native_enum=False), nullable=False, default=OutboxStatus.pending)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_retries: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error_code: Mapped[str | None] = mapped_column(String(255))
    last_error_message: Mapped[str | None] = mapped_column(Text)
    last_error_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ApiIdempotencyKey(UuidPrimaryKeyMixin, CreatedAtMixin, UpdatedAtMixin, BaseModel):
    __tablename__ = "api_idempotency_key"
    __table_args__ = (
        UniqueConstraint("endpoint_key", "actor_ref", "idempotency_key", name="uq_api_idempotency_key_scope"),
    )

    endpoint_key: Mapped[str] = mapped_column(String(255), nullable=False)
    actor_ref: Mapped[str] = mapped_column(String(255), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="in_progress")
    response_status_code: Mapped[int | None] = mapped_column(Integer)
    response_jsonb: Mapped[dict | None] = mapped_column(JSONB)
    resource_type: Mapped[str | None] = mapped_column(String(128))
    resource_id: Mapped[str | None] = mapped_column(String(255))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TranscriptRevision(UuidPrimaryKeyMixin, CreatedAtMixin, BaseModel):
    __tablename__ = "transcript_revision"
    __table_args__ = (
        UniqueConstraint("job_id", "version_no", name="uq_transcript_revision_job_version"),
    )

    job_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("job.id"), nullable=False)
    stage_run_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("stage_run.id"), nullable=False)
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    is_current: Mapped[bool] = mapped_column(nullable=False, default=True)
    provider: Mapped[str] = mapped_column(String(128), nullable=False)
    provider_version: Mapped[str] = mapped_column(String(128), nullable=False)
    language: Mapped[str | None] = mapped_column(String(32))
    adapter_metadata_jsonb: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)


class TranscriptWord(BaseModel):
    __tablename__ = "transcript_word"

    transcript_revision_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("transcript_revision.id"), primary_key=True)
    seq_no: Mapped[int] = mapped_column(Integer, primary_key=True)
    start_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    end_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    token: Mapped[str] = mapped_column(Text, nullable=False)
    speaker: Mapped[str | None] = mapped_column(String(128))
    confidence: Mapped[float | None] = mapped_column(Numeric(5, 4))


class TranscriptSegment(BaseModel):
    __tablename__ = "transcript_segment"

    transcript_revision_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("transcript_revision.id"), primary_key=True)
    seq_no: Mapped[int] = mapped_column(Integer, primary_key=True)
    start_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    end_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    speaker: Mapped[str | None] = mapped_column(String(128))
    text: Mapped[str] = mapped_column(Text, nullable=False)
    pause_before_ms: Mapped[int | None] = mapped_column(BigInteger)
    pause_after_ms: Mapped[int | None] = mapped_column(BigInteger)
    energy_score: Mapped[float | None] = mapped_column(Numeric(5, 4))


class StageRunArtifact(CreatedAtMixin, BaseModel):
    __tablename__ = "stage_run_artifact"

    stage_run_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("stage_run.id"), primary_key=True)
    artifact_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("artifact_object.id"), primary_key=True)
    role: Mapped[str] = mapped_column(String(64), primary_key=True)


class EvalSet(UuidPrimaryKeyMixin, CreatedAtMixin, BaseModel):
    __tablename__ = "eval_set"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[EvalSetStatus] = mapped_column(Enum(EvalSetStatus, native_enum=False), nullable=False)


class EvalSetMember(CreatedAtMixin, BaseModel):
    __tablename__ = "eval_set_member"

    eval_set_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("eval_set.id"), primary_key=True)
    source_video_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("source_video.id"), primary_key=True)


class CandidateLabel(UuidPrimaryKeyMixin, CreatedAtMixin, BaseModel):
    __tablename__ = "candidate_label"

    eval_set_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("eval_set.id"), nullable=False)
    source_video_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("source_video.id"), nullable=False)
    start_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    end_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    label: Mapped[CandidateLabelValue] = mapped_column(Enum(CandidateLabelValue, native_enum=False), nullable=False)
    actor_ref: Mapped[str] = mapped_column(String(255), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)


class BenchmarkRun(UuidPrimaryKeyMixin, CreatedAtMixin, BaseModel):
    __tablename__ = "benchmark_run"

    eval_set_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("eval_set.id"), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(128), nullable=False)
    scoring_policy_version: Mapped[str] = mapped_column(String(128), nullable=False)
    artifact_id: Mapped[UUID | None] = mapped_column(PGUUID(as_uuid=True), ForeignKey("artifact_object.id"))


class BenchmarkResult(UuidPrimaryKeyMixin, CreatedAtMixin, BaseModel):
    __tablename__ = "benchmark_result"

    benchmark_run_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("benchmark_run.id"), nullable=False)
    source_video_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("source_video.id"), nullable=False)
    metric_name: Mapped[str] = mapped_column(String(128), nullable=False)
    metric_value: Mapped[float] = mapped_column(Numeric(12, 4), nullable=False)


class CandidateSet(UuidPrimaryKeyMixin, CreatedAtMixin, BaseModel):
    __tablename__ = "candidate_set"
    __table_args__ = (
        UniqueConstraint("job_id", "version_no", name="uq_candidate_set_job_version"),
    )

    job_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("job.id"), nullable=False)
    stage_run_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("stage_run.id"), nullable=False)
    transcript_revision_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("transcript_revision.id"), nullable=False)
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    is_current: Mapped[bool] = mapped_column(nullable=False, default=True)
    scoring_policy_version: Mapped[str] = mapped_column(String(128), nullable=False)


class CandidateClip(UuidPrimaryKeyMixin, CreatedAtMixin, BaseModel):
    __tablename__ = "candidate_clip"
    __table_args__ = (
        UniqueConstraint("candidate_set_id", "rank_no", name="uq_candidate_clip_set_rank"),
        Index("ix_candidate_clip_job_final_score", "job_id", "final_score"),
        Index("ix_candidate_clip_set_duplicate_group", "candidate_set_id", "duplicate_group"),
        Index("ix_candidate_clip_set_topic_cluster", "candidate_set_id", "topic_cluster"),
    )

    candidate_set_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("candidate_set.id"), nullable=False)
    job_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), ForeignKey("job.id"), nullable=False)
    rank_no: Mapped[int] = mapped_column(Integer, nullable=False)
    start_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    end_ms: Mapped[int] = mapped_column(BigInteger, nullable=False)
    hook_score: Mapped[float] = mapped_column(Numeric(5, 4), nullable=False)
    semantic_score: Mapped[float] = mapped_column(Numeric(5, 4), nullable=False)
    audio_score: Mapped[float] = mapped_column(Numeric(5, 4), nullable=False)
    visual_score: Mapped[float] = mapped_column(Numeric(5, 4), nullable=False)
    llm_score: Mapped[float] = mapped_column(Numeric(5, 4), nullable=False)
    final_score: Mapped[float] = mapped_column(Numeric(5, 4), nullable=False)
    duplicate_group: Mapped[str | None] = mapped_column(String(128))
    topic_cluster: Mapped[str | None] = mapped_column(String(128))
    length_bucket: Mapped[str] = mapped_column(String(32), nullable=False)
    rationale_jsonb: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
