"""Core tenant-consistent foreign-key regression checks."""

import os

import pytest
from sqlalchemy import ForeignKeyConstraint, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

from ops_pilot.models.approval import ApprovalRequest
from ops_pilot.models.order import OperationalOrder
from ops_pilot.models.payment_transaction import PaymentTransaction


def assert_composite_fk(
    model: type,
    name: str,
    columns: set[str],
) -> None:
    constraints = [
        constraint
        for constraint in model.__table__.constraints
        if isinstance(constraint, ForeignKeyConstraint) and constraint.name == name
    ]

    assert len(constraints) == 1
    assert {column.name for column in constraints[0].columns} == columns


def test_order_customer_tenant_fk() -> None:
    assert_composite_fk(
        OperationalOrder,
        "fk_operational_orders_customer_tenant",
        {"customer_id", "organization_id"},
    )


def test_payment_order_tenant_fk() -> None:
    assert_composite_fk(
        PaymentTransaction,
        "fk_payment_transactions_order_tenant",
        {"order_id", "organization_id"},
    )


def test_payment_source_tenant_fk() -> None:
    assert_composite_fk(
        PaymentTransaction,
        "fk_payment_transactions_source_tenant",
        {"source_transaction_id", "organization_id"},
    )


def test_approval_incident_tenant_fk() -> None:
    assert_composite_fk(
        ApprovalRequest,
        "fk_approval_requests_incident_tenant",
        {"incident_id", "organization_id"},
    )


@pytest.mark.integration
@pytest.mark.anyio
async def test_postgresql_tenant_constraints_are_installed() -> None:
    database_url = os.getenv("OPSPILOT_INTEGRATION_DATABASE_URL")

    if not database_url:
        pytest.skip("Integration database URL not configured")

    if os.getenv("OPSPILOT_DEDICATED_TEST_DB") != "YES":
        pytest.skip("Dedicated test database confirmation required")

    if make_url(database_url).get_backend_name() != "postgresql":
        pytest.fail("PostgreSQL integration database required")

    expected = {
        "fk_operational_orders_customer_tenant",
        "fk_payment_transactions_order_tenant",
        "fk_payment_transactions_source_tenant",
        "fk_approval_requests_incident_tenant",
    }

    engine = create_async_engine(database_url)

    try:
        async with engine.connect() as connection:
            result = await connection.execute(
                text(
                    """
                    SELECT conname
                    FROM pg_constraint
                    WHERE conname = ANY(:names)
                      AND contype = 'f'
                      AND convalidated
                    """
                ),
                {"names": list(expected)},
            )

            installed = set(result.scalars().all())

            assert installed == expected
    finally:
        await engine.dispose()
