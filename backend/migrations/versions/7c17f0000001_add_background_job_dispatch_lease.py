"""Add fenced dispatch leases for background jobs.

Revision ID: 7c17f0000001
Revises: 63e1ab15030f
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "7c17f0000001"
down_revision: str | Sequence[str] | None = "63e1ab15030f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "background_jobs",
        sa.Column(
            "dispatch_lease_token",
            sa.UUID(),
            nullable=True,
        ),
    )
    op.add_column(
        "background_jobs",
        sa.Column(
            "dispatch_lease_expires_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column(
        "background_jobs",
        "dispatch_lease_expires_at",
    )
    op.drop_column(
        "background_jobs",
        "dispatch_lease_token",
    )
