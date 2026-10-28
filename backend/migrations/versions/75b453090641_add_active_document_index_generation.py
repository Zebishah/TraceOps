"""add active document index generation

Revision ID: 75b453090641
Revises: e5b7ed5034e0
Create Date: 2026-10-28 16:23:32.434227

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "75b453090641"
down_revision: str | Sequence[str] | None = "e5b7ed5034e0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "documents",
        sa.Column(
            "active_index_generation",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("documents", "active_index_generation")
