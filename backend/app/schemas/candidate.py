from datetime import datetime
from uuid import UUID

from app.schemas.common import AppSchema


class CandidateClipOut(AppSchema):
    id: UUID
    candidate_set_id: UUID
    job_id: UUID
    rank_no: int
    start_ms: int
    end_ms: int
    hook_score: float
    semantic_score: float
    audio_score: float
    visual_score: float
    llm_score: float
    final_score: float
    duplicate_group: str | None
    topic_cluster: str | None
    length_bucket: str
    rationale_jsonb: dict
    created_at: datetime
