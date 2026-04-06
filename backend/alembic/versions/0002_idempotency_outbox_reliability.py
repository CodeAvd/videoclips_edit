"""outbox_reliability

Revision ID: 0002_outbox_reliability
Revises: 0001_m0_m1_baseline
Create Date: 2026-04-05 00:30:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "0002_outbox_reliability"
down_revision = "0001_m0_m1_baseline"
branch_labels = None
depends_on = None


def upgrade() -> None:
    uuid_type = postgresql.UUID(as_uuid=True)
    json_type = postgresql.JSONB(astext_type=sa.Text())

    op.add_column("outbox_event", sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("outbox_event", sa.Column("max_retries", sa.Integer(), nullable=False, server_default="5"))
    op.add_column("outbox_event", sa.Column("lease_expires_at", sa.DateTime(timezone=True)))
    op.add_column("outbox_event", sa.Column("last_error_code", sa.String(length=255)))
    op.add_column("outbox_event", sa.Column("last_error_message", sa.Text()))
    op.add_column("outbox_event", sa.Column("last_error_at", sa.DateTime(timezone=True)))
    op.create_index("ix_outbox_event_lease_expires_at", "outbox_event", ["lease_expires_at"])

    op.create_table(
        "api_idempotency_key",
        sa.Column("id", uuid_type, primary_key=True, nullable=False),
        sa.Column("endpoint_key", sa.String(length=255), nullable=False),
        sa.Column("actor_ref", sa.String(length=255), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=False),
        sa.Column("request_fingerprint", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("response_status_code", sa.Integer()),
        sa.Column("response_jsonb", json_type),
        sa.Column("resource_type", sa.String(length=128)),
        sa.Column("resource_id", sa.String(length=255)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.UniqueConstraint("endpoint_key", "actor_ref", "idempotency_key", name="uq_api_idempotency_key_scope"),
    )


def downgrade() -> None:
    op.drop_table("api_idempotency_key")
    op.drop_index("ix_outbox_event_lease_expires_at", table_name="outbox_event")
    op.drop_column("outbox_event", "last_error_at")
    op.drop_column("outbox_event", "last_error_message")
    op.drop_column("outbox_event", "last_error_code")
    op.drop_column("outbox_event", "lease_expires_at")
    op.drop_column("outbox_event", "max_retries")
    op.drop_column("outbox_event", "retry_count")
