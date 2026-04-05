"""m2_smart_clipping

Revision ID: 0003_m2_smart_clipping
Revises: 0002_idempotency_outbox_reliability
Create Date: 2026-04-05 00:45:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0003_m2_smart_clipping"
down_revision = "0002_idempotency_outbox_reliability"
branch_labels = None
depends_on = None


def upgrade() -> None:
    uuid_type = postgresql.UUID(as_uuid=True)
    json_type = postgresql.JSONB(astext_type=sa.Text())

    op.add_column("transcript_revision", sa.Column("language", sa.String(length=32), nullable=True))
    op.add_column(
        "transcript_revision",
        sa.Column("adapter_metadata_jsonb", json_type, nullable=False, server_default=sa.text("'{}'::jsonb")),
    )
    op.alter_column("transcript_revision", "adapter_metadata_jsonb", server_default=None)

    op.create_table(
        "candidate_set",
        sa.Column("id", uuid_type, primary_key=True, nullable=False),
        sa.Column("job_id", uuid_type, sa.ForeignKey("job.id"), nullable=False),
        sa.Column("stage_run_id", uuid_type, sa.ForeignKey("stage_run.id"), nullable=False),
        sa.Column("transcript_revision_id", uuid_type, sa.ForeignKey("transcript_revision.id"), nullable=False),
        sa.Column("version_no", sa.Integer(), nullable=False),
        sa.Column("is_current", sa.Boolean(), nullable=False),
        sa.Column("scoring_policy_version", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("job_id", "version_no", name="uq_candidate_set_job_version"),
    )
    op.create_index(
        "uq_candidate_set_current",
        "candidate_set",
        ["job_id"],
        unique=True,
        postgresql_where=sa.text("is_current = true"),
    )

    op.create_table(
        "candidate_clip",
        sa.Column("id", uuid_type, primary_key=True, nullable=False),
        sa.Column("candidate_set_id", uuid_type, sa.ForeignKey("candidate_set.id"), nullable=False),
        sa.Column("job_id", uuid_type, sa.ForeignKey("job.id"), nullable=False),
        sa.Column("rank_no", sa.Integer(), nullable=False),
        sa.Column("start_ms", sa.BigInteger(), nullable=False),
        sa.Column("end_ms", sa.BigInteger(), nullable=False),
        sa.Column("hook_score", sa.Numeric(5, 4), nullable=False),
        sa.Column("semantic_score", sa.Numeric(5, 4), nullable=False),
        sa.Column("audio_score", sa.Numeric(5, 4), nullable=False),
        sa.Column("visual_score", sa.Numeric(5, 4), nullable=False),
        sa.Column("llm_score", sa.Numeric(5, 4), nullable=False),
        sa.Column("final_score", sa.Numeric(5, 4), nullable=False),
        sa.Column("duplicate_group", sa.String(length=128), nullable=True),
        sa.Column("topic_cluster", sa.String(length=128), nullable=True),
        sa.Column("length_bucket", sa.String(length=32), nullable=False),
        sa.Column("rationale_jsonb", json_type, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("candidate_set_id", "rank_no", name="uq_candidate_clip_set_rank"),
    )
    op.create_index("ix_candidate_clip_job_final_score", "candidate_clip", ["job_id", "final_score"])
    op.create_index("ix_candidate_clip_set_duplicate_group", "candidate_clip", ["candidate_set_id", "duplicate_group"])
    op.create_index("ix_candidate_clip_set_topic_cluster", "candidate_clip", ["candidate_set_id", "topic_cluster"])


def downgrade() -> None:
    for index_name, table_name in [
        ("ix_candidate_clip_set_topic_cluster", "candidate_clip"),
        ("ix_candidate_clip_set_duplicate_group", "candidate_clip"),
        ("ix_candidate_clip_job_final_score", "candidate_clip"),
        ("uq_candidate_set_current", "candidate_set"),
    ]:
        op.drop_index(index_name, table_name=table_name)

    op.drop_table("candidate_clip")
    op.drop_table("candidate_set")
    op.drop_column("transcript_revision", "adapter_metadata_jsonb")
    op.drop_column("transcript_revision", "language")
