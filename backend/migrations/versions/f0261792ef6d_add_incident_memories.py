"""add incident memories

Revision ID: f0261792ef6d
Revises: 5d753ed9ef23
Create Date: 2026-10-06 16:01:58.088042

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f0261792ef6d"
down_revision: str | Sequence[str] | None = "5d753ed9ef23"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "incident_memories",
        sa.Column(
            "id",
            sa.UUID(),
            nullable=False,
        ),
        sa.Column(
            "organization_id",
            sa.UUID(),
            nullable=False,
        ),
        sa.Column(
            "incident_id",
            sa.UUID(),
            nullable=False,
        ),
        sa.Column(
            "subject_customer_id",
            sa.UUID(),
            nullable=True,
        ),
        sa.Column(
            "category",
            sa.String(length=100),
            nullable=False,
        ),
        sa.Column(
            "summary",
            sa.Text(),
            nullable=False,
        ),
        sa.Column(
            "resolution",
            sa.Text(),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["incident_id"],
            ["incidents.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["subject_customer_id"],
            ["customers.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint(
            "id",
        ),
        sa.UniqueConstraint(
            "incident_id",
            name="uq_incident_memories_incident_id",
        ),
    )

    op.create_index(
        op.f("ix_incident_memories_category"),
        "incident_memories",
        ["category"],
        unique=False,
    )

    op.create_index(
        op.f("ix_incident_memories_incident_id"),
        "incident_memories",
        ["incident_id"],
        unique=False,
    )

    op.create_index(
        op.f("ix_incident_memories_organization_id"),
        "incident_memories",
        ["organization_id"],
        unique=False,
    )

    op.create_index(
        op.f("ix_incident_memories_subject_customer_id"),
        "incident_memories",
        ["subject_customer_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_incident_memories_subject_customer_id"),
        table_name="incident_memories",
    )

    op.drop_index(
        op.f("ix_incident_memories_organization_id"),
        table_name="incident_memories",
    )

    op.drop_index(
        op.f("ix_incident_memories_incident_id"),
        table_name="incident_memories",
    )

    op.drop_index(
        op.f("ix_incident_memories_category"),
        table_name="incident_memories",
    )

    op.drop_table(
        "incident_memories",
    )
