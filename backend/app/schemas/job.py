from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.models.enums import JobStatus, Platform, StageName, StageRunStatus
from app.schemas.common import AppSchema, TimestampedOut


class CreateJobRequest(BaseModel):
    source_video_id: UUID
    target_platforms: list[Platform]
    target_final_clip_count: int = Field(ge=1, le=10)
    publish_mode: str
    prompt_version: str = "v1"
    scoring_policy_version: str = "v1"
    shortlist_target_count: int = Field(default=8, ge=1, le=20)


class JobAcceptedOut(AppSchema):
    job_id: UUID
    status: JobStatus
    current_job_config_snapshot_id: UUID


class JobOut(AppSchema):
    id: UUID
    source_video_id: UUID
    brand_profile_id: UUID
    target_final_clip_count: int
    status: JobStatus
    prompt_version: str
    scoring_policy_version: str
    version: int
    created_at: datetime
    updated_at: datetime


class JobConfigSnapshotOut(TimestampedOut):
    id: UUID
    job_id: UUID
    version_no: int
    is_current: bool
    checksum: str
    target_final_clip_count: int
    shortlist_target_count: int
    prompt_version: str
    scoring_policy_version: str
    config_jsonb: dict


class JobStageSummaryOut(AppSchema):
    stage_name: StageName
    latest_stage_run_id: UUID
    latest_attempt_no: int
    latest_status: StageRunStatus
    latest_started_at: datetime | None
    latest_ended_at: datetime | None
    latest_error_code: str | None


class JobOutputCountsOut(AppSchema):
    transcript_revision_count: int = 0
    transcript_segment_count: int = 0
    transcript_word_count: int = 0
    candidate_set_count: int = 0
    candidate_clip_count: int = 0


class JobApprovalStateOut(AppSchema):
    shortlist_review: str
    final_approval: str


class JobDetailOut(JobOut):
    current_job_config_snapshot_id: UUID | None = None
    current_config_snapshot: JobConfigSnapshotOut | None = None
    stage_summary: list[JobStageSummaryOut] = Field(default_factory=list)
    output_counts: JobOutputCountsOut = Field(default_factory=JobOutputCountsOut)
    current_approval_state: JobApprovalStateOut


class StageRunOut(AppSchema):
    id: UUID
    job_id: UUID
    stage_name: StageName
    attempt_no: int
    status: StageRunStatus
    worker_id: str | None
    lease_expires_at: datetime | None
    started_at: datetime | None
    ended_at: datetime | None
    error_code: str | None
    created_at: datetime


class ResolveIntakeReviewRequest(BaseModel):
    decision: str
    reason_code: str | None = None
