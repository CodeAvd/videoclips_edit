from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.models.enums import JobStatus, Platform, StageName, StageRunStatus
from app.schemas.common import AppSchema


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
