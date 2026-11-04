"""Durable training queue and serialized worker control.

Revision ID: 9e30f0000001
Revises: 8d29e0000001
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "9e30f0000001"
down_revision = "8d29e0000001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "training_control",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True)),
        sa.Column("device", sa.String(8)),
    )
    op.execute("INSERT INTO training_control (id) VALUES (1)")
    op.create_table(
        "training_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "organization_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "created_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
        ),
        sa.Column("request_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("dataset", postgresql.JSONB(), nullable=False),
        sa.Column("progress", postgresql.JSONB(), nullable=False),
        sa.Column("metrics", postgresql.JSONB()),
        sa.Column("error_code", sa.String(60)),
        sa.Column("lease_token", postgresql.UUID(as_uuid=True)),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column("artifact_key", sa.Text()),
        sa.Column("artifact_sha256", sa.String(64)),
        sa.Column("artifact_bytes", sa.Integer()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("organization_id", "request_id", name="uq_training_request"),
        sa.CheckConstraint(
            "status IN ('queued','running','cancel_requested','cancelled','succeeded','failed')",
            name="ck_training_status",
        ),
    )
    op.create_index("ix_training_runs_organization_id", "training_runs", ["organization_id"])
    op.create_index("ix_training_runs_status", "training_runs", ["status"])


def downgrade() -> None:
    op.drop_table("training_runs")
    op.drop_table("training_control")
