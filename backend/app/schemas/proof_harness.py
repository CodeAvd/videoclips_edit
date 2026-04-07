from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator

from app.models.enums import (
    EvalSetStatus,
    ProofDecisionValue,
    ProofRejectReasonCode,
    ProofReviewStatus,
    ProofShortlistSystem,
)
from app.schemas.common import AppSchema, TimestampedOut


PROOF_SHORTLIST_SIZE = 8
PROOF_BATCH_CODES = ("A", "B", "C")


class EvalSetCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    status: EvalSetStatus = EvalSetStatus.draft


class EvalSetOut(TimestampedOut):
    id: UUID
    name: str
    status: EvalSetStatus


class EvalSetMemberCreateRequest(BaseModel):
    source_video_id: UUID
    metadata_jsonb: dict = Field(default_factory=dict)


class EvalSetMemberOut(TimestampedOut):
    eval_set_id: UUID
    source_video_id: UUID
    metadata_jsonb: dict


class ProofShortlistCandidateInput(BaseModel):
    start_ms: int = Field(ge=0)
    end_ms: int = Field(gt=0)
    rationale_jsonb: dict = Field(default_factory=dict)
    duplicate_group: str | None = None
    topic_cluster: str | None = None
    length_bucket: str | None = None
    metadata_jsonb: dict = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_window(self) -> "ProofShortlistCandidateInput":
        if self.end_ms <= self.start_ms:
            raise ValueError("end_ms must be greater than start_ms.")
        return self


class CreateEngineProofShortlistRequest(BaseModel):
    eval_set_id: UUID | None = None


class BaselineShortlistImportRequest(BaseModel):
    system_name: ProofShortlistSystem
    eval_set_id: UUID | None = None
    generation_time_seconds: int | None = Field(default=None, ge=0, le=3600)
    metadata_jsonb: dict = Field(default_factory=dict)
    candidates: list[ProofShortlistCandidateInput]

    @field_validator("system_name")
    @classmethod
    def validate_system_name(cls, value: ProofShortlistSystem) -> ProofShortlistSystem:
        if value == ProofShortlistSystem.engine:
            raise ValueError("Baseline import supports only manual or vizard systems.")
        return value

    @field_validator("candidates")
    @classmethod
    def validate_candidate_count(cls, value: list[ProofShortlistCandidateInput]) -> list[ProofShortlistCandidateInput]:
        if len(value) != PROOF_SHORTLIST_SIZE:
            raise ValueError(f"Exactly {PROOF_SHORTLIST_SIZE} candidates are required.")
        return value


class ProofShortlistCandidateOut(TimestampedOut):
    id: UUID
    rank_no: int
    start_ms: int
    end_ms: int
    transcript_excerpt: str
    duplicate_group: str | None
    topic_cluster: str | None
    length_bucket: str | None
    rationale_jsonb: dict
    metadata_jsonb: dict
    preview_artifact_id: UUID | None = None
    preview_storage_key: str | None = None


class ProofReviewCandidateOut(AppSchema):
    id: UUID
    rank_no: int
    start_ms: int
    end_ms: int
    transcript_excerpt: str
    preview_artifact_id: UUID | None = None
    preview_storage_key: str | None = None


class ProofShortlistOut(TimestampedOut):
    id: UUID
    source_video_id: UUID
    job_id: UUID | None = None
    eval_set_id: UUID | None = None
    system_name: ProofShortlistSystem
    version_no: int
    is_current: bool
    candidate_count: int
    generation_time_seconds: int | None = None
    actor_ref: str | None = None
    prompt_version: str | None = None
    scoring_policy_version: str | None = None
    metadata_jsonb: dict
    artifact_id: UUID | None = None
    artifact_storage_key: str | None = None
    candidates: list[ProofShortlistCandidateOut] = Field(default_factory=list)


class ProofReviewSessionCreateRequest(BaseModel):
    eval_set_id: UUID
    source_video_id: UUID
    is_audit: bool = False
    time_budget_seconds: int = Field(default=600, ge=60, le=3600)


class ProofReviewBatchOut(AppSchema):
    batch_code: str
    display_order: int
    elapsed_review_seconds: int | None = None
    candidates: list[ProofReviewCandidateOut] = Field(default_factory=list)


class ProofReviewSessionOut(AppSchema):
    id: UUID
    eval_set_id: UUID
    source_video_id: UUID
    status: ProofReviewStatus
    time_budget_seconds: int
    protocol_version: str
    batches: list[ProofReviewBatchOut] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class ProofReviewCandidateDecisionInput(BaseModel):
    proof_shortlist_candidate_id: UUID
    decision: ProofDecisionValue
    reject_reason_code: ProofRejectReasonCode | None = None
    rationale_helpful: bool
    notes: str | None = None

    @model_validator(mode="after")
    def validate_reason_code(self) -> "ProofReviewCandidateDecisionInput":
        if self.decision == ProofDecisionValue.reject and self.reject_reason_code is None:
            raise ValueError("reject_reason_code is required for rejected candidates.")
        if self.decision == ProofDecisionValue.approve and self.reject_reason_code is not None:
            raise ValueError("reject_reason_code must be omitted for approved candidates.")
        return self


class ProofReviewBatchSubmissionInput(BaseModel):
    batch_code: str
    elapsed_review_seconds: int = Field(ge=0, le=3600)
    candidate_decisions: list[ProofReviewCandidateDecisionInput]

    @field_validator("batch_code")
    @classmethod
    def validate_batch_code(cls, value: str) -> str:
        if value not in PROOF_BATCH_CODES:
            raise ValueError(f"batch_code must be one of {', '.join(PROOF_BATCH_CODES)}.")
        return value

    @field_validator("candidate_decisions")
    @classmethod
    def validate_candidate_decision_count(
        cls,
        value: list[ProofReviewCandidateDecisionInput],
    ) -> list[ProofReviewCandidateDecisionInput]:
        if len(value) != PROOF_SHORTLIST_SIZE:
            raise ValueError(f"Each batch requires exactly {PROOF_SHORTLIST_SIZE} candidate decisions.")
        return value


class CompleteProofReviewSessionRequest(BaseModel):
    batch_reviews: list[ProofReviewBatchSubmissionInput]
    batch_preference_ranking: list[str]

    @model_validator(mode="after")
    def validate_batches(self) -> "CompleteProofReviewSessionRequest":
        batch_codes = [item.batch_code for item in self.batch_reviews]
        if sorted(batch_codes) != sorted(PROOF_BATCH_CODES):
            raise ValueError(f"batch_reviews must include exactly {', '.join(PROOF_BATCH_CODES)}.")
        if sorted(self.batch_preference_ranking) != sorted(PROOF_BATCH_CODES):
            raise ValueError(f"batch_preference_ranking must include exactly {', '.join(PROOF_BATCH_CODES)}.")
        if len(set(self.batch_preference_ranking)) != len(PROOF_BATCH_CODES):
            raise ValueError("batch_preference_ranking must not contain duplicates.")
        return self


class ProofComparisonRunCreateRequest(BaseModel):
    eval_set_id: UUID


class ProofComparisonRunOut(TimestampedOut):
    id: UUID
    eval_set_id: UUID
    artifact_id: UUID | None = None
    artifact_storage_key: str | None = None
    actor_ref: str | None = None
    protocol_version: str
    payload: dict
