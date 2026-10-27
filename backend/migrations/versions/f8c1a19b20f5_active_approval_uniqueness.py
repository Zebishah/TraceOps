"""Prevent multiple active approvals for one incident.

Revision ID: f8c1a19b20f5
Revises: e7c1a19b20f4
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f8c1a19b20f5"
down_revision: str | Sequence[str] | None = "e7c1a19b20f4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


INDEX_NAME = "uq_approval_one_active_per_incident"


def upgrade() -> None:
    bind = op.get_bind()

    conflicts = bind.execute(
        sa.text(
            """
            SELECT incident_id, count(*) AS active_count
            FROM approval_requests
            WHERE status IN ('pending', 'approved')
            GROUP BY incident_id
            HAVING count(*) > 1
            LIMIT 1
            """
        )
    ).first()

    if conflicts is not None:
        raise RuntimeError(
            "Cannot add active approval uniqueness: unreconciled duplicate approvals remain"
        )

    op.create_index(
        INDEX_NAME,
        "approval_requests",
        ["incident_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('pending', 'approved')"),
    )


def downgrade() -> None:
    op.drop_index(
        INDEX_NAME,
        table_name="approval_requests",
    )
