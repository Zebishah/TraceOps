"""Enforce tenant consistency for core financial relationships.

Revision ID: a9d62b4e3106
Revises: f8c1a19b20f5
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a9d62b4e3106"
down_revision: str | Sequence[str] | None = "f8c1a19b20f5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


PREFLIGHT = (
    (
        "Order-to-customer tenant mismatch",
        """
        SELECT o.id
        FROM operational_orders o
        JOIN customers c ON c.id = o.customer_id
        WHERE o.organization_id <> c.organization_id
        LIMIT 1
        """,
    ),
    (
        "Payment-to-order tenant mismatch",
        """
        SELECT p.id
        FROM operational_payment_transactions p
        JOIN operational_orders o ON o.id = p.order_id
        WHERE p.organization_id <> o.organization_id
        LIMIT 1
        """,
    ),
    (
        "Refund-to-source tenant mismatch",
        """
        SELECT p.id
        FROM operational_payment_transactions p
        JOIN operational_payment_transactions source
          ON source.id = p.source_transaction_id
        WHERE p.organization_id <> source.organization_id
        LIMIT 1
        """,
    ),
    (
        "Approval-to-incident tenant mismatch",
        """
        SELECT a.id
        FROM approval_requests a
        JOIN incidents i ON i.id = a.incident_id
        WHERE a.organization_id <> i.organization_id
        LIMIT 1
        """,
    ),
)


def upgrade() -> None:
    bind = op.get_bind()

    # Never silently repair, move, or delete financial data.
    for description, statement in PREFLIGHT:
        conflicting_id = bind.execute(sa.text(statement)).scalar_one_or_none()

        if conflicting_id is not None:
            raise RuntimeError(
                f"{description}: conflicting record {conflicting_id}. "
                "Resolve the tenant-integrity conflict before migration."
            )

    op.create_unique_constraint(
        "uq_customers_id_organization",
        "customers",
        ["id", "organization_id"],
    )
    op.create_unique_constraint(
        "uq_operational_orders_id_organization",
        "operational_orders",
        ["id", "organization_id"],
    )
    op.create_unique_constraint(
        "uq_payment_transactions_id_organization",
        "operational_payment_transactions",
        ["id", "organization_id"],
    )
    op.create_unique_constraint(
        "uq_incidents_id_organization",
        "incidents",
        ["id", "organization_id"],
    )

    op.create_foreign_key(
        "fk_operational_orders_customer_tenant",
        "operational_orders",
        "customers",
        ["customer_id", "organization_id"],
        ["id", "organization_id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_payment_transactions_order_tenant",
        "operational_payment_transactions",
        "operational_orders",
        ["order_id", "organization_id"],
        ["id", "organization_id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_payment_transactions_source_tenant",
        "operational_payment_transactions",
        "operational_payment_transactions",
        ["source_transaction_id", "organization_id"],
        ["id", "organization_id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_approval_requests_incident_tenant",
        "approval_requests",
        "incidents",
        ["incident_id", "organization_id"],
        ["id", "organization_id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_approval_requests_incident_tenant",
        "approval_requests",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_payment_transactions_source_tenant",
        "operational_payment_transactions",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_payment_transactions_order_tenant",
        "operational_payment_transactions",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_operational_orders_customer_tenant",
        "operational_orders",
        type_="foreignkey",
    )

    op.drop_constraint(
        "uq_incidents_id_organization",
        "incidents",
        type_="unique",
    )
    op.drop_constraint(
        "uq_payment_transactions_id_organization",
        "operational_payment_transactions",
        type_="unique",
    )
    op.drop_constraint(
        "uq_operational_orders_id_organization",
        "operational_orders",
        type_="unique",
    )
    op.drop_constraint(
        "uq_customers_id_organization",
        "customers",
        type_="unique",
    )
