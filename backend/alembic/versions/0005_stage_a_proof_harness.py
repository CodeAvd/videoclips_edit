"""stage_a_proof_harness

Revision ID: 0005_stage_a_proof_harness
Revises: 0004_m2_eval_harness
Create Date: 2026-04-06 03:10:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0005_stage_a_proof_harness"
down_revision = "0004_m2_eval_harness"
branch_labels = None
depends_on = None


def upgrade() -> None:
    uuid_type = postgresql.UUID(as_uuid=True)
    jsonb_type = postgresql.JSONB(astext_type=sa.Text())

    proof_shortlist_system = sa.Enum("engine", "manual", "vizard", name="proofshortlistsystem", native_enum=False)
    proof_review_status = sa.Enum("in_progress", "completed", name="proofreviewstatus", native_enum=False)
    proof_decision_value = sa.Enum("approve", "reject", name="proofdecisionvalue", native_enum=False)
    proof_reject_reason_code = sa.Enum(
        "weak_opening",
        "late_or_missing_payoff",
        "needs_context",
        "fragmented_cut",
        "duplicate_angle",
        "off_topic_or_low_signal",
        "review_timeout",
        name="proofrejectreasoncode",
        native_enum=False,
    )

    op.add_column(
        "eval_set_member",
        sa.Column(
            "metadata_jsonb",
            jsonb_type,
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )

    op.create_table(
        "proof_shortlist",
        sa.Column("id", uuid_type, primary_key=True, nullable=False),
        sa.Column("source_video_id", uuid_type, sa.ForeignKey("source_video.id"), nullable=False),
        sa.Column("job_id", uuid_type, sa.ForeignKey("job.id"), nullable=True),
        sa.Column("eval_set_id", uuid_type, sa.ForeignKey("eval_set.id"), nullable=True),
        sa.Column("system_name", proof_shortlist_system, nullable=False),
        sa.Column("version_no", sa.Integer(), nullable=False),
        sa.Column("is_current", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("candidate_count", sa.Integer(), nullable=False),
        sa.Column("generation_time_seconds", sa.Integer(), nullable=True),
        sa.Column("source_candidate_set_id", uuid_type, sa.ForeignKey("candidate_set.id"), nullable=True),
        sa.Column("artifact_id", uuid_type, sa.ForeignKey("artifact_object.id"), nullable=True),
        sa.Column("actor_ref", sa.String(length=255), nullable=True),
        sa.Column("prompt_version", sa.String(length=128), nullable=True),
        sa.Column("scoring_policy_version", sa.String(length=128), nullable=True),
        sa.Column("metadata_jsonb", jsonb_type, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("source_video_id", "system_name", "version_no", name="uq_proof_shortlist_source_system_version"),
    )
    op.create_index(
        "ix_proof_shortlist_source_system_current",
        "proof_shortlist",
        ["source_video_id", "system_name", "is_current"],
    )

    op.create_table(
        "proof_shortlist_candidate",
        sa.Column("id", uuid_type, primary_key=True, nullable=False),
        sa.Column("proof_shortlist_id", uuid_type, sa.ForeignKey("proof_shortlist.id"), nullable=False),
        sa.Column("source_candidate_clip_id", uuid_type, sa.ForeignKey("candidate_clip.id"), nullable=True),
        sa.Column("rank_no", sa.Integer(), nullable=False),
        sa.Column("start_ms", sa.BigInteger(), nullable=False),
        sa.Column("end_ms", sa.BigInteger(), nullable=False),
        sa.Column("transcript_excerpt", sa.Text(), nullable=False, server_default=""),
        sa.Column("duplicate_group", sa.String(length=128), nullable=True),
        sa.Column("topic_cluster", sa.String(length=128), nullable=True),
        sa.Column("length_bucket", sa.String(length=32), nullable=True),
        sa.Column("rationale_jsonb", jsonb_type, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("metadata_jsonb", jsonb_type, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("preview_artifact_id", uuid_type, sa.ForeignKey("artifact_object.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("proof_shortlist_id", "rank_no", name="uq_proof_shortlist_candidate_rank"),
    )
    op.create_index(
        "ix_proof_shortlist_candidate_shortlist",
        "proof_shortlist_candidate",
        ["proof_shortlist_id", "rank_no"],
    )

    op.create_table(
        "proof_review_session",
        sa.Column("id", uuid_type, primary_key=True, nullable=False),
        sa.Column("eval_set_id", uuid_type, sa.ForeignKey("eval_set.id"), nullable=False),
        sa.Column("source_video_id", uuid_type, sa.ForeignKey("source_video.id"), nullable=False),
        sa.Column("reviewer_actor_ref", sa.String(length=255), nullable=False),
        sa.Column("status", proof_review_status, nullable=False, server_default="in_progress"),
        sa.Column("time_budget_seconds", sa.Integer(), nullable=False, server_default="600"),
        sa.Column("is_audit", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("protocol_version", sa.String(length=64), nullable=False, server_default="stage_a_v1"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )

    op.create_table(
        "proof_review_batch",
        sa.Column("proof_review_session_id", uuid_type, sa.ForeignKey("proof_review_session.id"), primary_key=True, nullable=False),
        sa.Column("batch_code", sa.String(length=1), primary_key=True, nullable=False),
        sa.Column("proof_shortlist_id", uuid_type, sa.ForeignKey("proof_shortlist.id"), nullable=False),
        sa.Column("system_name", proof_shortlist_system, nullable=False),
        sa.Column("display_order", sa.Integer(), nullable=False),
        sa.Column("elapsed_review_seconds", sa.Integer(), nullable=True),
        sa.UniqueConstraint("proof_review_session_id", "batch_code", name="uq_proof_review_batch_code"),
        sa.UniqueConstraint("proof_review_session_id", "proof_shortlist_id", name="uq_proof_review_batch_shortlist"),
    )

    op.create_table(
        "proof_review_decision",
        sa.Column("id", uuid_type, primary_key=True, nullable=False),
        sa.Column("proof_review_session_id", uuid_type, sa.ForeignKey("proof_review_session.id"), nullable=False),
        sa.Column("batch_code", sa.String(length=1), nullable=False),
        sa.Column("proof_shortlist_candidate_id", uuid_type, sa.ForeignKey("proof_shortlist_candidate.id"), nullable=False),
        sa.Column("decision", proof_decision_value, nullable=False),
        sa.Column("reject_reason_code", proof_reject_reason_code, nullable=True),
        sa.Column("rationale_helpful", sa.Boolean(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("proof_review_session_id", "proof_shortlist_candidate_id", name="uq_proof_review_decision_candidate"),
    )
    op.create_index(
        "ix_proof_review_decision_session_batch",
        "proof_review_decision",
        ["proof_review_session_id", "batch_code"],
    )

    op.create_table(
        "proof_review_preference",
        sa.Column("proof_review_session_id", uuid_type, sa.ForeignKey("proof_review_session.id"), primary_key=True, nullable=False),
        sa.Column("rank_no", sa.Integer(), primary_key=True, nullable=False),
        sa.Column("batch_code", sa.String(length=1), nullable=False),
        sa.UniqueConstraint("proof_review_session_id", "rank_no", name="uq_proof_review_preference_rank"),
    )

    op.create_table(
        "proof_comparison_run",
        sa.Column("id", uuid_type, primary_key=True, nullable=False),
        sa.Column("eval_set_id", uuid_type, sa.ForeignKey("eval_set.id"), nullable=False),
        sa.Column("artifact_id", uuid_type, sa.ForeignKey("artifact_object.id"), nullable=True),
        sa.Column("actor_ref", sa.String(length=255), nullable=True),
        sa.Column("protocol_version", sa.String(length=64), nullable=False, server_default="stage_a_v1"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )

    op.create_table(
        "proof_comparison_result",
        sa.Column("id", uuid_type, primary_key=True, nullable=False),
        sa.Column("proof_comparison_run_id", uuid_type, sa.ForeignKey("proof_comparison_run.id"), nullable=False),
        sa.Column("source_video_id", uuid_type, sa.ForeignKey("source_video.id"), nullable=False),
        sa.Column("system_name", proof_shortlist_system, nullable=False),
        sa.Column("metric_name", sa.String(length=128), nullable=False),
        sa.Column("metric_value", sa.Numeric(12, 4), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )
    op.create_index(
        "ix_proof_comparison_result_run_source_system",
        "proof_comparison_result",
        ["proof_comparison_run_id", "source_video_id", "system_name"],
    )


def downgrade() -> None:
    op.drop_index("ix_proof_comparison_result_run_source_system", table_name="proof_comparison_result")
    op.drop_table("proof_comparison_result")
    op.drop_table("proof_comparison_run")
    op.drop_table("proof_review_preference")
    op.drop_index("ix_proof_review_decision_session_batch", table_name="proof_review_decision")
    op.drop_table("proof_review_decision")
    op.drop_table("proof_review_batch")
    op.drop_table("proof_review_session")
    op.drop_index("ix_proof_shortlist_candidate_shortlist", table_name="proof_shortlist_candidate")
    op.drop_table("proof_shortlist_candidate")
    op.drop_index("ix_proof_shortlist_source_system_current", table_name="proof_shortlist")
    op.drop_table("proof_shortlist")
    op.drop_column("eval_set_member", "metadata_jsonb")
