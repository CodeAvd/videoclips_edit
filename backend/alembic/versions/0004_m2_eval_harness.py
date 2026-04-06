"""m2_eval_harness

Revision ID: 0004_m2_eval_harness
Revises: 0003_m2_smart_clipping
Create Date: 2026-04-06 00:45:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0004_m2_eval_harness"
down_revision = "0003_m2_smart_clipping"
branch_labels = None
depends_on = None


def upgrade() -> None:
    uuid_type = postgresql.UUID(as_uuid=True)
    eval_set_status = sa.Enum("draft", "frozen", "archived", name="evalsetstatus", native_enum=False)
    candidate_label_value = sa.Enum("accept", "reject", name="candidatelabelvalue", native_enum=False)

    op.create_table(
        "eval_set",
        sa.Column("id", uuid_type, primary_key=True, nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("status", eval_set_status, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )

    op.create_table(
        "eval_set_member",
        sa.Column("eval_set_id", uuid_type, sa.ForeignKey("eval_set.id"), primary_key=True, nullable=False),
        sa.Column("source_video_id", uuid_type, sa.ForeignKey("source_video.id"), primary_key=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )

    op.create_table(
        "candidate_label",
        sa.Column("id", uuid_type, primary_key=True, nullable=False),
        sa.Column("eval_set_id", uuid_type, sa.ForeignKey("eval_set.id"), nullable=False),
        sa.Column("source_video_id", uuid_type, sa.ForeignKey("source_video.id"), nullable=False),
        sa.Column("start_ms", sa.BigInteger(), nullable=False),
        sa.Column("end_ms", sa.BigInteger(), nullable=False),
        sa.Column("label", candidate_label_value, nullable=False),
        sa.Column("actor_ref", sa.String(length=255), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )

    op.create_table(
        "benchmark_run",
        sa.Column("id", uuid_type, primary_key=True, nullable=False),
        sa.Column("eval_set_id", uuid_type, sa.ForeignKey("eval_set.id"), nullable=False),
        sa.Column("prompt_version", sa.String(length=128), nullable=False),
        sa.Column("scoring_policy_version", sa.String(length=128), nullable=False),
        sa.Column("artifact_id", uuid_type, sa.ForeignKey("artifact_object.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )

    op.create_table(
        "benchmark_result",
        sa.Column("id", uuid_type, primary_key=True, nullable=False),
        sa.Column("benchmark_run_id", uuid_type, sa.ForeignKey("benchmark_run.id"), nullable=False),
        sa.Column("source_video_id", uuid_type, sa.ForeignKey("source_video.id"), nullable=False),
        sa.Column("metric_name", sa.String(length=128), nullable=False),
        sa.Column("metric_value", sa.Numeric(12, 4), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("benchmark_result")
    op.drop_table("benchmark_run")
    op.drop_table("candidate_label")
    op.drop_table("eval_set_member")
    op.drop_table("eval_set")
