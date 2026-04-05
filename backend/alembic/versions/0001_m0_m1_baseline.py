"""m0_m1_baseline

Revision ID: 0001_m0_m1_baseline
Revises: None
Create Date: 2026-04-05 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0001_m0_m1_baseline"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    uuid_type = postgresql.UUID(as_uuid=True)
    json_type = postgresql.JSONB(astext_type=sa.Text())

    op.create_table(
        "artifact_object",
        sa.Column("id", uuid_type, primary_key=True, nullable=False),
        sa.Column("storage_key", sa.String(length=512), nullable=False),
        sa.Column("kind", sa.Enum("upload", "source_video", "normalized_audio", "proxy_video", "thumbnails", "asr_payload", "stage_artifact", name="artifactkind", native_enum=False), nullable=False),
        sa.Column("sha256", sa.String(length=128), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("mime_type", sa.String(length=255), nullable=False),
        sa.Column("metadata_jsonb", json_type, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("storage_key", name="uq_artifact_object_storage_key"),
    )

    op.create_table(
        "upload_session",
        sa.Column("id", uuid_type, primary_key=True, nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("content_type", sa.String(length=255), nullable=False),
        sa.Column("declared_size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("declared_sha256", sa.String(length=128)),
        sa.Column("storage_key", sa.String(length=512), nullable=False),
        sa.Column("status", sa.Enum("created", "completed", "expired", name="uploadstatus", native_enum=False), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_artifact_id", uuid_type, sa.ForeignKey("artifact_object.id")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("storage_key", name="uq_upload_session_storage_key"),
    )

    op.create_table(
        "brand_profile",
        sa.Column("id", uuid_type, primary_key=True, nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("language", sa.String(length=32), nullable=False),
        sa.Column("caption_style_defaults", json_type, nullable=False),
        sa.Column("overlay_policy", json_type, nullable=False),
        sa.Column("music_policy", json_type, nullable=False),
        sa.Column("platform_defaults", json_type, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("name", name="uq_brand_profile_name"),
    )

    op.create_table(
        "platform_account",
        sa.Column("id", uuid_type, primary_key=True, nullable=False),
        sa.Column("brand_profile_id", uuid_type, sa.ForeignKey("brand_profile.id"), nullable=False),
        sa.Column("platform", sa.Enum("youtube_shorts", "instagram_reels", "tiktok", name="platform", native_enum=False), nullable=False),
        sa.Column("channel_name", sa.String(length=255), nullable=False),
        sa.Column("connection_ref", sa.String(length=255), nullable=False),
        sa.Column("capabilities_jsonb", json_type, nullable=False),
        sa.Column("status", sa.Enum("active", "paused", "revoked", "invalid", name="platformaccountstatus", native_enum=False), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("brand_profile_id", "platform", "channel_name", name="uq_platform_account_brand_platform_channel"),
    )

    op.create_table(
        "source_video",
        sa.Column("id", uuid_type, primary_key=True, nullable=False),
        sa.Column("brand_profile_id", uuid_type, sa.ForeignKey("brand_profile.id"), nullable=False),
        sa.Column("canonical_asset_id", uuid_type, sa.ForeignKey("artifact_object.id"), nullable=False),
        sa.Column("source_type", sa.Enum("uploaded_asset", "approved_import", name="sourcetype", native_enum=False), nullable=False),
        sa.Column("duration_ms", sa.BigInteger()),
        sa.Column("language", sa.String(length=32)),
        sa.Column("speaker_count_estimate", sa.Integer()),
        sa.Column("rights_attestation", sa.Boolean(), nullable=False),
        sa.Column("ingest_status", sa.Enum("pending", "accepted", "manual_review_required", "rejected_out_of_scope", "processing", "ready", "failed", name="ingeststatus", native_enum=False), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )

    op.create_table(
        "source_video_provenance",
        sa.Column("id", uuid_type, primary_key=True, nullable=False),
        sa.Column("source_video_id", uuid_type, sa.ForeignKey("source_video.id"), nullable=False),
        sa.Column("provenance_type", sa.Enum("approved_import", "manual_attestation", "channel_allowlist", name="provenancetype", native_enum=False), nullable=False),
        sa.Column("provider", sa.String(length=255)),
        sa.Column("source_uri", sa.Text()),
        sa.Column("evidence_artifact_id", uuid_type, sa.ForeignKey("artifact_object.id")),
        sa.Column("approved_by", sa.String(length=255)),
        sa.Column("approved_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )

    op.create_table(
        "source_video_artifact",
        sa.Column("source_video_id", uuid_type, sa.ForeignKey("source_video.id"), primary_key=True, nullable=False),
        sa.Column("artifact_id", uuid_type, sa.ForeignKey("artifact_object.id"), primary_key=True, nullable=False),
        sa.Column("role", sa.String(length=64), primary_key=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )

    op.create_table(
        "job",
        sa.Column("id", uuid_type, primary_key=True, nullable=False),
        sa.Column("source_video_id", uuid_type, sa.ForeignKey("source_video.id"), nullable=False),
        sa.Column("brand_profile_id", uuid_type, sa.ForeignKey("brand_profile.id"), nullable=False),
        sa.Column("target_final_clip_count", sa.Integer(), nullable=False),
        sa.Column("status", sa.Enum("created", "processing", "awaiting_manual_review", "awaiting_shortlist_review", "rendering_finals", "qa_manual_salvage_required", "awaiting_final_approval", "publishing", "metrics_ingesting", "completed", "completed_partial", "completed_insufficient_output", "failed", "cancelled", name="jobstatus", native_enum=False), nullable=False),
        sa.Column("prompt_version", sa.String(length=128), nullable=False),
        sa.Column("scoring_policy_version", sa.String(length=128), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )

    op.create_table(
        "job_target_platform",
        sa.Column("job_id", uuid_type, sa.ForeignKey("job.id"), primary_key=True, nullable=False),
        sa.Column("platform", sa.Enum("youtube_shorts", "instagram_reels", "tiktok", name="platform_target", native_enum=False), primary_key=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )

    op.create_table(
        "job_config_snapshot",
        sa.Column("id", uuid_type, primary_key=True, nullable=False),
        sa.Column("job_id", uuid_type, sa.ForeignKey("job.id"), nullable=False),
        sa.Column("version_no", sa.Integer(), nullable=False),
        sa.Column("is_current", sa.Boolean(), nullable=False),
        sa.Column("checksum", sa.String(length=128), nullable=False),
        sa.Column("target_final_clip_count", sa.Integer(), nullable=False),
        sa.Column("shortlist_target_count", sa.Integer(), nullable=False),
        sa.Column("prompt_version", sa.String(length=128), nullable=False),
        sa.Column("scoring_policy_version", sa.String(length=128), nullable=False),
        sa.Column("config_jsonb", json_type, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("job_id", "version_no", name="uq_job_config_snapshot_job_version"),
    )
    op.create_index(
        "uq_job_config_snapshot_current",
        "job_config_snapshot",
        ["job_id"],
        unique=True,
        postgresql_where=sa.text("is_current = true"),
    )

    op.create_table(
        "stage_run",
        sa.Column("id", uuid_type, primary_key=True, nullable=False),
        sa.Column("job_id", uuid_type, sa.ForeignKey("job.id"), nullable=False),
        sa.Column("stage_name", sa.Enum("intake", "ingest", "transcript", "feature_extract", "ranking", "preview_render", "final_render", "qa", "publish", "metrics", name="stagename", native_enum=False), nullable=False),
        sa.Column("attempt_no", sa.Integer(), nullable=False),
        sa.Column("status", sa.Enum("queued", "claimed", "running", "succeeded", "failed_retryable", "failed_terminal", "blocked_manual_review", "cancelled", name="stagerunstatus", native_enum=False), nullable=False),
        sa.Column("worker_id", sa.String(length=255)),
        sa.Column("lease_token", sa.String(length=255)),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("ended_at", sa.DateTime(timezone=True)),
        sa.Column("error_code", sa.String(length=255)),
        sa.Column("cost_usd", sa.Numeric(12, 4)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("job_id", "stage_name", "attempt_no", name="uq_stage_run_job_stage_attempt"),
    )
    op.create_index("ix_stage_run_job_stage_status", "stage_run", ["job_id", "stage_name", "status"])
    op.create_index("ix_stage_run_lease_expires_at", "stage_run", ["lease_expires_at"])
    op.create_index(
        "uq_stage_run_active",
        "stage_run",
        ["job_id", "stage_name"],
        unique=True,
        postgresql_where=sa.text("status in ('queued','claimed','running')"),
    )

    op.create_table(
        "job_status_transition",
        sa.Column("id", uuid_type, primary_key=True, nullable=False),
        sa.Column("job_id", uuid_type, sa.ForeignKey("job.id"), nullable=False),
        sa.Column("from_status", sa.Enum("created", "processing", "awaiting_manual_review", "awaiting_shortlist_review", "rendering_finals", "qa_manual_salvage_required", "awaiting_final_approval", "publishing", "metrics_ingesting", "completed", "completed_partial", "completed_insufficient_output", "failed", "cancelled", name="jobstatus_transition", native_enum=False)),
        sa.Column("to_status", sa.Enum("created", "processing", "awaiting_manual_review", "awaiting_shortlist_review", "rendering_finals", "qa_manual_salvage_required", "awaiting_final_approval", "publishing", "metrics_ingesting", "completed", "completed_partial", "completed_insufficient_output", "failed", "cancelled", name="jobstatus_transition_to", native_enum=False), nullable=False),
        sa.Column("stage_run_id", uuid_type, sa.ForeignKey("stage_run.id")),
        sa.Column("actor_type", sa.String(length=64)),
        sa.Column("actor_ref", sa.String(length=255)),
        sa.Column("reason_code", sa.String(length=255)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )

    op.create_table(
        "outbox_event",
        sa.Column("id", uuid_type, primary_key=True, nullable=False),
        sa.Column("aggregate_type", sa.String(length=128), nullable=False),
        sa.Column("aggregate_id", sa.String(length=255), nullable=False),
        sa.Column("event_type", sa.String(length=255), nullable=False),
        sa.Column("dedupe_key", sa.String(length=255), nullable=False),
        sa.Column("payload_jsonb", json_type, nullable=False),
        sa.Column("status", sa.Enum("pending", "claimed", "processed", "failed", name="outboxstatus", native_enum=False), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("claimed_at", sa.DateTime(timezone=True)),
        sa.Column("processed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("dedupe_key", name="uq_outbox_event_dedupe_key"),
    )
    op.create_index("ix_outbox_event_status_available_at", "outbox_event", ["status", "available_at"])

    op.create_table(
        "transcript_revision",
        sa.Column("id", uuid_type, primary_key=True, nullable=False),
        sa.Column("job_id", uuid_type, sa.ForeignKey("job.id"), nullable=False),
        sa.Column("stage_run_id", uuid_type, sa.ForeignKey("stage_run.id"), nullable=False),
        sa.Column("version_no", sa.Integer(), nullable=False),
        sa.Column("is_current", sa.Boolean(), nullable=False),
        sa.Column("provider", sa.String(length=128), nullable=False),
        sa.Column("provider_version", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("job_id", "version_no", name="uq_transcript_revision_job_version"),
    )
    op.create_index(
        "uq_transcript_revision_current",
        "transcript_revision",
        ["job_id"],
        unique=True,
        postgresql_where=sa.text("is_current = true"),
    )

    op.create_table(
        "transcript_word",
        sa.Column("transcript_revision_id", uuid_type, sa.ForeignKey("transcript_revision.id"), primary_key=True, nullable=False),
        sa.Column("seq_no", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("start_ms", sa.BigInteger(), nullable=False),
        sa.Column("end_ms", sa.BigInteger(), nullable=False),
        sa.Column("token", sa.Text(), nullable=False),
        sa.Column("speaker", sa.String(length=128)),
        sa.Column("confidence", sa.Numeric(5, 4)),
    )
    op.create_index("ix_transcript_word_revision_start_ms", "transcript_word", ["transcript_revision_id", "start_ms"])

    op.create_table(
        "transcript_segment",
        sa.Column("transcript_revision_id", uuid_type, sa.ForeignKey("transcript_revision.id"), primary_key=True, nullable=False),
        sa.Column("seq_no", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("start_ms", sa.BigInteger(), nullable=False),
        sa.Column("end_ms", sa.BigInteger(), nullable=False),
        sa.Column("speaker", sa.String(length=128)),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("pause_before_ms", sa.BigInteger()),
        sa.Column("pause_after_ms", sa.BigInteger()),
        sa.Column("energy_score", sa.Numeric(5, 4)),
    )
    op.create_index("ix_transcript_segment_revision_start_ms", "transcript_segment", ["transcript_revision_id", "start_ms"])

    op.create_table(
        "stage_run_artifact",
        sa.Column("stage_run_id", uuid_type, sa.ForeignKey("stage_run.id"), primary_key=True, nullable=False),
        sa.Column("artifact_id", uuid_type, sa.ForeignKey("artifact_object.id"), primary_key=True, nullable=False),
        sa.Column("role", sa.String(length=64), primary_key=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )


def downgrade() -> None:
    for index_name, table_name in [
        ("ix_transcript_segment_revision_start_ms", "transcript_segment"),
        ("ix_transcript_word_revision_start_ms", "transcript_word"),
        ("uq_transcript_revision_current", "transcript_revision"),
        ("ix_outbox_event_status_available_at", "outbox_event"),
        ("uq_stage_run_active", "stage_run"),
        ("ix_stage_run_lease_expires_at", "stage_run"),
        ("ix_stage_run_job_stage_status", "stage_run"),
        ("uq_job_config_snapshot_current", "job_config_snapshot"),
    ]:
        op.drop_index(index_name, table_name=table_name)

    for table_name in [
        "stage_run_artifact",
        "transcript_segment",
        "transcript_word",
        "transcript_revision",
        "outbox_event",
        "job_status_transition",
        "stage_run",
        "job_config_snapshot",
        "job_target_platform",
        "job",
        "source_video_artifact",
        "source_video_provenance",
        "source_video",
        "platform_account",
        "brand_profile",
        "upload_session",
        "artifact_object",
    ]:
        op.drop_table(table_name)
