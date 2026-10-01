"""link refunds to source transactions

Revision ID: 5d753ed9ef23
Revises: a8ada9c70fbb
Create Date: 2026-10-01 22:53:20.698701

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "5d753ed9ef23"
down_revision: str | Sequence[str] | None = "a8ada9c70fbb"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "operational_payment_transactions",
        sa.Column(
            "source_transaction_id",
            sa.UUID(),
            nullable=True,
        ),
    )

    op.create_index(
        "ix_operational_payment_transactions_source_transaction_id",
        "operational_payment_transactions",
        ["source_transaction_id"],
        unique=False,
    )

    op.create_unique_constraint(
        "uq_payment_transactions_source_transaction",
        "operational_payment_transactions",
        ["source_transaction_id"],
    )

    op.create_foreign_key(
        "fk_payment_transactions_source_transaction",
        "operational_payment_transactions",
        "operational_payment_transactions",
        ["source_transaction_id"],
        ["id"],
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_payment_transactions_source_transaction",
        "operational_payment_transactions",
        type_="foreignkey",
    )

    op.drop_constraint(
        "uq_payment_transactions_source_transaction",
        "operational_payment_transactions",
        type_="unique",
    )

    op.drop_index(
        "ix_operational_payment_transactions_source_transaction_id",
        table_name="operational_payment_transactions",
    )

    op.drop_column(
        "operational_payment_transactions",
        "source_transaction_id",
    )
