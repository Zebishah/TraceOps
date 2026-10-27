"""Verify PostgreSQL rejects cross-tenant references.

Requires an explicitly confirmed, separate PostgreSQL test database.
All created records are rolled back.
"""

import os
import uuid

import pytest
from dotenv import dotenv_values
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine


def _test_database_url() -> str:
    if os.environ.get("OPSPILOT_DEDICATED_TEST_DB") != "YES":
        pytest.skip("Dedicated test database confirmation required")

    values = dotenv_values(".env")

    main_url = values.get("DATABASE_URL")
    test_url = os.environ.get("OPSPILOT_TEST_DATABASE_URL") or values.get(
        "OPSPILOT_TEST_DATABASE_URL"
    )

    if not main_url or not test_url:
        pytest.skip("Main and test database URLs required")

    main = make_url(main_url)
    test = make_url(test_url)

    def identity(url):
        return (
            url.host,
            url.port or 5432,
            url.database,
            url.username,
        )

    if identity(main) == identity(test):
        pytest.fail("Refusing to test against the main database")

    if test.get_backend_name() != "postgresql":
        pytest.fail("A PostgreSQL test database is required")

    if "us-east-2.aws.neon.tech" not in (test.host or ""):
        pytest.fail("Unexpected test database endpoint")

    return test_url


@pytest.mark.anyio
async def test_database_rejects_cross_tenant_foreign_keys() -> None:
    engine = create_async_engine(_test_database_url())

    org_a = uuid.uuid4()
    org_b = uuid.uuid4()
    customer_a = uuid.uuid4()
    customer_b = uuid.uuid4()
    order_a = uuid.uuid4()
    order_b = uuid.uuid4()
    payment_b = uuid.uuid4()
    incident_b = uuid.uuid4()
    user_b = uuid.uuid4()

    async def execute(connection, statement, **values):
        return await connection.execute(
            text(statement),
            values,
        )

    async def expect_fk_rejection(
        connection,
        *,
        statement: str,
        expected_constraint: str,
        **values,
    ) -> None:
        # A savepoint lets us recover from the expected SQL error
        # without aborting the whole setup transaction.
        savepoint = await connection.begin_nested()

        try:
            with pytest.raises(IntegrityError) as error:
                await execute(connection, statement, **values)

            assert expected_constraint in str(error.value)
        finally:
            await savepoint.rollback()

    try:
        async with engine.connect() as connection:
            transaction = await connection.begin()

            try:
                for org_id, suffix in (
                    (org_a, "a"),
                    (org_b, "b"),
                ):
                    await execute(
                        connection,
                        """
                        INSERT INTO organizations (id, name, slug)
                        VALUES (:id, :name, :slug)
                        """,
                        id=org_id,
                        name=f"Security Test {suffix}",
                        slug=f"tenant-fk-{uuid.uuid4().hex}",
                    )

                await execute(
                    connection,
                    """
                    INSERT INTO users
                        (id, email, full_name, password_hash)
                    VALUES
                        (:id, :email, 'Security Test', 'not-a-real-hash')
                    """,
                    id=user_b,
                    email=f"tenant-{uuid.uuid4().hex}@example.test",
                )

                for customer_id, org_id in (
                    (customer_a, org_a),
                    (customer_b, org_b),
                ):
                    await execute(
                        connection,
                        """
                        INSERT INTO customers
                            (id, organization_id, external_customer_id)
                        VALUES (:id, :org, :external_id)
                        """,
                        id=customer_id,
                        org=org_id,
                        external_id=f"customer-{uuid.uuid4().hex}",
                    )

                for order_id, org_id, customer_id in (
                    (order_a, org_a, customer_a),
                    (order_b, org_b, customer_b),
                ):
                    await execute(
                        connection,
                        """
                        INSERT INTO operational_orders
                            (
                                id,
                                organization_id,
                                customer_id,
                                external_order_id,
                                total_amount,
                                currency,
                                status,
                                ordered_at
                            )
                        VALUES
                            (
                                :id, :org, :customer, :external_id,
                                100.00, 'USD', 'paid', NOW()
                            )
                        """,
                        id=order_id,
                        org=org_id,
                        customer=customer_id,
                        external_id=f"order-{uuid.uuid4().hex}",
                    )

                await execute(
                    connection,
                    """
                    INSERT INTO operational_payment_transactions
                        (
                            id, organization_id, order_id,
                            external_transaction_id, provider,
                            transaction_type, amount, currency, status
                        )
                    VALUES
                        (
                            :id, :org, :order_id, :external_id,
                            'test', 'charge', 100.00, 'USD', 'succeeded'
                        )
                    """,
                    id=payment_b,
                    org=org_b,
                    order_id=order_b,
                    external_id=f"payment-{uuid.uuid4().hex}",
                )

                await execute(
                    connection,
                    """
                    INSERT INTO incidents
                        (
                            id, organization_id, created_by_user_id,
                            title, description, status
                        )
                    VALUES
                        (
                            :id, :org, :user_id,
                            'Tenant test', 'Temporary incident', 'new'
                        )
                    """,
                    id=incident_b,
                    org=org_b,
                    user_id=user_b,
                )

                await expect_fk_rejection(
                    connection,
                    statement="""
                        INSERT INTO operational_orders
                            (
                                id, organization_id, customer_id,
                                external_order_id, total_amount,
                                currency, status, ordered_at
                            )
                        VALUES
                            (
                                :id, :org, :customer, :external_id,
                                10.00, 'USD', 'paid', NOW()
                            )
                    """,
                    expected_constraint=("fk_operational_orders_customer_tenant"),
                    id=uuid.uuid4(),
                    org=org_a,
                    customer=customer_b,
                    external_id=f"bad-order-{uuid.uuid4().hex}",
                )

                await expect_fk_rejection(
                    connection,
                    statement="""
                        INSERT INTO operational_payment_transactions
                            (
                                id, organization_id, order_id,
                                external_transaction_id, provider,
                                transaction_type, amount,
                                currency, status
                            )
                        VALUES
                            (
                                :id, :org, :order_id, :external_id,
                                'test', 'charge', 10.00,
                                'USD', 'succeeded'
                            )
                    """,
                    expected_constraint=("fk_payment_transactions_order_tenant"),
                    id=uuid.uuid4(),
                    org=org_a,
                    order_id=order_b,
                    external_id=f"bad-payment-{uuid.uuid4().hex}",
                )

                await expect_fk_rejection(
                    connection,
                    statement="""
                        INSERT INTO operational_payment_transactions
                            (
                                id, organization_id, order_id,
                                source_transaction_id,
                                external_transaction_id, provider,
                                transaction_type, amount,
                                currency, status
                            )
                        VALUES
                            (
                                :id, :org, :order_id, :source_id,
                                :external_id, 'test', 'refund',
                                10.00, 'USD', 'succeeded'
                            )
                    """,
                    expected_constraint=("fk_payment_transactions_source_tenant"),
                    id=uuid.uuid4(),
                    org=org_a,
                    order_id=order_a,
                    source_id=payment_b,
                    external_id=f"bad-refund-{uuid.uuid4().hex}",
                )

                await expect_fk_rejection(
                    connection,
                    statement="""
                        INSERT INTO approval_requests
                            (
                                id, organization_id, incident_id,
                                workflow_thread_id, action_type,
                                action_payload, reason, status
                            )
                        VALUES
                            (
                                :id, :org, :incident_id,
                                :thread_id, 'refund_transaction',
                                '{}'::jsonb, 'Tenant isolation test',
                                'pending'
                            )
                    """,
                    expected_constraint=("fk_approval_requests_incident_tenant"),
                    id=uuid.uuid4(),
                    org=org_a,
                    incident_id=incident_b,
                    thread_id=f"test-{uuid.uuid4().hex}",
                )

            finally:
                # Never commit test data to the shared database.
                await transaction.rollback()

    finally:
        await engine.dispose()
