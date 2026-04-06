from enum import StrEnum


class ActorRole(StrEnum):
    viewer = "viewer"
    reviewer = "reviewer"
    operator = "operator"
    admin = "admin"


class UploadStatus(StrEnum):
    created = "created"
    completed = "completed"
    expired = "expired"


class ArtifactKind(StrEnum):
    upload = "upload"
    source_video = "source_video"
    normalized_audio = "normalized_audio"
    proxy_video = "proxy_video"
    thumbnails = "thumbnails"
    asr_payload = "asr_payload"
    stage_artifact = "stage_artifact"


class SourceVideoArtifactRole(StrEnum):
    source_asset = "source_asset"
    canonical_video = "canonical_video"
    proxy_video = "proxy_video"
    normalized_audio = "normalized_audio"
    thumbnails = "thumbnails"


class EvalSetStatus(StrEnum):
    draft = "draft"
    frozen = "frozen"
    archived = "archived"


class CandidateLabelValue(StrEnum):
    accept = "accept"
    reject = "reject"


class Platform(StrEnum):
    youtube_shorts = "youtube_shorts"
    instagram_reels = "instagram_reels"
    tiktok = "tiktok"


class PlatformAccountStatus(StrEnum):
    active = "active"
    paused = "paused"
    revoked = "revoked"
    invalid = "invalid"


class SourceType(StrEnum):
    uploaded_asset = "uploaded_asset"
    approved_import = "approved_import"


class ProvenanceType(StrEnum):
    approved_import = "approved_import"
    manual_attestation = "manual_attestation"
    channel_allowlist = "channel_allowlist"


class IngestStatus(StrEnum):
    pending = "pending"
    accepted = "accepted"
    manual_review_required = "manual_review_required"
    rejected_out_of_scope = "rejected_out_of_scope"
    processing = "processing"
    ready = "ready"
    failed = "failed"


class JobStatus(StrEnum):
    created = "created"
    processing = "processing"
    awaiting_manual_review = "awaiting_manual_review"
    awaiting_shortlist_review = "awaiting_shortlist_review"
    rendering_finals = "rendering_finals"
    qa_manual_salvage_required = "qa_manual_salvage_required"
    awaiting_final_approval = "awaiting_final_approval"
    publishing = "publishing"
    metrics_ingesting = "metrics_ingesting"
    completed = "completed"
    completed_partial = "completed_partial"
    completed_insufficient_output = "completed_insufficient_output"
    failed = "failed"
    cancelled = "cancelled"


class StageName(StrEnum):
    intake = "intake"
    ingest = "ingest"
    transcript = "transcript"
    feature_extract = "feature_extract"
    ranking = "ranking"
    preview_render = "preview_render"
    final_render = "final_render"
    qa = "qa"
    publish = "publish"
    metrics = "metrics"


class StageRunStatus(StrEnum):
    queued = "queued"
    claimed = "claimed"
    running = "running"
    succeeded = "succeeded"
    failed_retryable = "failed_retryable"
    failed_terminal = "failed_terminal"
    blocked_manual_review = "blocked_manual_review"
    cancelled = "cancelled"


class OutboxStatus(StrEnum):
    pending = "pending"
    claimed = "claimed"
    processed = "processed"
    failed = "failed"
