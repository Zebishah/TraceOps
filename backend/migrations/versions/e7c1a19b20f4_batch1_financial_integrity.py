"""Batch 1: reusable financial and approval schema.

Revision ID: e7c1a19b20f4
Revises: b720a001
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e7c1a19b20f4"
down_revision: str | Sequence[str] | None = "b720a001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()

    invalid_amounts = bind.execute(
        sa.text(
            """
            SELECT count(*)
            FROM operational_payment_transactions
            WHERE amount <= 0
            """
        )
    ).scalar_one()

    if invalid_amounts:
        raise RuntimeError("Cannot migrate: nonpositive financial amounts exist")

    # Preserve every historical approval while extending
    # the lifecycle vocabulary.
    op.drop_constraint(
        "ck_approval_requests_status",
        "approval_requests",
        type_="check",
    )

    op.create_check_constraint(
        "ck_approval_requests_status",
        "approval_requests",
        "status IN ('pending', 'approved', 'rejected', 'executed', 'failed', 'superseded')",
    )

    op.add_column(
        "approval_requests",
        sa.Column(
            "superseded_by_approval_id",
            sa.UUID(),
            nullable=True,
        ),
    )

    op.add_column(
        "approval_requests",
        sa.Column(
            "superseded_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )

    op.add_column(
        "approval_requests",
        sa.Column(
            "supersession_reason",
            sa.Text(),
            nullable=True,
        ),
    )

    op.create_foreign_key(
        "fk_approvals_superseded_by",
        "approval_requests",
        "approval_requests",
        ["superseded_by_approval_id"],
        ["id"],
        ondelete="RESTRICT",
    )

    op.create_check_constraint(
        "ck_approvals_supersession_metadata",
        "approval_requests",
        """
        (
            status = 'superseded'
            AND superseded_by_approval_id IS NOT NULL
            AND superseded_at IS NOT NULL
            AND supersession_reason IS NOT NULL
            AND length(trim(supersession_reason)) > 0
        )
        OR
        (
            status <> 'superseded'
            AND superseded_by_approval_id IS NULL
            AND superseded_at IS NULL
            AND supersession_reason IS NULL
        )
        """,
    )

    op.create_check_constraint(
        "ck_payment_transactions_amount_positive",
        "operational_payment_transactions",
        "amount > 0",
    )

    # Stop deleting customer orders as a side effect
    # of deleting a customer.
    op.drop_constraint(
        "operational_orders_customer_id_fkey",
        "operational_orders",
        type_="foreignkey",
    )

    op.create_foreign_key(
        "fk_operational_orders_customer_restrict",
        "operational_orders",
        "customers",
        ["customer_id"],
        ["id"],
        ondelete="RESTRICT",
    )

    # Stop deleting financial transactions as a side
    # effect of deleting an order.
    op.drop_constraint(
        "operational_payment_transactions_order_id_fkey",
        "operational_payment_transactions",
        type_="foreignkey",
    )

    op.create_foreign_key(
        "fk_payment_transactions_order_restrict",
        "operational_payment_transactions",
        "operational_orders",
        ["order_id"],
        ["id"],
        ondelete="RESTRICT",
    )

    # IMPORTANT:
    # The partial unique index is intentionally NOT created
    # here because legacy active duplicates may still exist.
    # The final migration adds it after reconciliation.


def downgrade() -> None:
    bind = op.get_bind()

    superseded_count = bind.execute(
        sa.text(
            """
            SELECT count(*)
            FROM approval_requests
            WHERE status = 'superseded'
            """
        )
    ).scalar_one()

    if superseded_count:
        raise RuntimeError("Cannot downgrade while superseded approval history exists")

    op.drop_constraint(
        "fk_payment_transactions_order_restrict",
        "operational_payment_transactions",
        type_="foreignkey",
    )

    op.create_foreign_key(
        "operational_payment_transactions_order_id_fkey",
        "operational_payment_transactions",
        "operational_orders",
        ["order_id"],
        ["id"],
        ondelete="CASCADE",
    )

    op.drop_constraint(
        "fk_operational_orders_customer_restrict",
        "operational_orders",
        type_="foreignkey",
    )

    op.create_foreign_key(
        "operational_orders_customer_id_fkey",
        "operational_orders",
        "customers",
        ["customer_id"],
        ["id"],
        ondelete="CASCADE",
    )

    op.drop_constraint(
        "ck_payment_transactions_amount_positive",
        "operational_payment_transactions",
        type_="check",
    )

    op.drop_constraint(
        "ck_approvals_supersession_metadata",
        "approval_requests",
        type_="check",
    )

    op.drop_constraint(
        "fk_approvals_superseded_by",
        "approval_requests",
        type_="foreignkey",
    )

    op.drop_column(
        "approval_requests",
        "supersession_reason",
    )

    op.drop_column(
        "approval_requests",
        "superseded_at",
    )

    op.drop_column(
        "approval_requests",
        "superseded_by_approval_id",
    )

    op.drop_constraint(
        "ck_approval_requests_status",
        "approval_requests",
        type_="check",
    )

    op.create_check_constraint(
        "ck_approval_requests_status",
        "approval_requests",
        "status IN ('pending', 'approved', 'rejected', 'executed', 'failed')",
    )
