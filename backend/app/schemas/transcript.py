from uuid import UUID

from app.schemas.common import AppSchema


class TranscriptWordOut(AppSchema):
    transcript_revision_id: UUID
    seq_no: int
    start_ms: int
    end_ms: int
    token: str
    speaker: str | None
    confidence: float | None


class TranscriptSegmentOut(AppSchema):
    transcript_revision_id: UUID
    seq_no: int
    start_ms: int
    end_ms: int
    speaker: str | None
    text: str
    pause_before_ms: int | None
    pause_after_ms: int | None
    energy_score: float | None
