"""Add durable approval resume jobs.

Revision ID: b720a001
Revises: 13f9055c9b1f
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b720a001"
down_revision: str | Sequence[str] | None = "13f9055c9b1f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "approval_resume_jobs",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column(
            "organization_id",
            sa.UUID(),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "incident_id",
            sa.UUID(),
            sa.ForeignKey("incidents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "approval_request_id",
            sa.UUID(),
            sa.ForeignKey("approval_requests.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default="pending",
        ),
        sa.Column(
            "attempts",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "next_attempt_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("lease_token", sa.UUID(), nullable=True),
        sa.Column(
            "lease_expires_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "last_error",
            sa.String(1000),
            nullable=True,
        ),
        sa.Column(
            "completed_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "approval_request_id",
            name="uq_approval_resume_jobs_approval",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'processing', 'completed', 'failed')",
            name="ck_approval_resume_jobs_status",
        ),
        sa.CheckConstraint(
            "attempts >= 0",
            name="ck_approval_resume_jobs_attempts",
        ),
    )

    op.create_index(
        "ix_approval_resume_jobs_organization_id",
        "approval_resume_jobs",
        ["organization_id"],
    )

    op.create_index(
        "ix_approval_resume_jobs_incident_id",
        "approval_resume_jobs",
        ["incident_id"],
    )

    op.create_index(
        "ix_approval_resume_jobs_due",
        "approval_resume_jobs",
        ["status", "next_attempt_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_approval_resume_jobs_due",
        table_name="approval_resume_jobs",
    )
    op.drop_index(
        "ix_approval_resume_jobs_incident_id",
        table_name="approval_resume_jobs",
    )
    op.drop_index(
        "ix_approval_resume_jobs_organization_id",
        table_name="approval_resume_jobs",
    )
    op.drop_table("approval_resume_jobs")
