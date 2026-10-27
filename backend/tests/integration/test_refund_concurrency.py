"""PostgreSQL refund concurrency and idempotency integration test.

Uses a dedicated disposable PostgreSQL database only.
"""

import asyncio
import os
import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ops_pilot.models.approval import (
    ApprovalActionType,
    ApprovalRequest,
    ApprovalStatus,
)
from ops_pilot.models.customer import Customer
from ops_pilot.models.incident import Incident, IncidentStatus
from ops_pilot.models.order import OperationalOrder, OrderStatus
from ops_pilot.models.organization import Organization
from ops_pilot.models.payment_transaction import (
    PaymentTransaction,
    PaymentTransactionStatus,
    PaymentTransactionType,
)
from ops_pilot.models.user import User
from ops_pilot.services.refund_execution import execute_approved_refund


def test_concurrent_retries_create_exactly_one_refund() -> None:
    database_url = os.getenv("OPSPILOT_INTEGRATION_DATABASE_URL")

    if not database_url:
        pytest.skip("OPSPILOT_INTEGRATION_DATABASE_URL is required")

    if os.getenv("OPSPILOT_DEDICATED_TEST_DB") != "YES":
        pytest.skip("Dedicated test database confirmation required")

    if os.getenv("OPSPILOT_ALLOW_SHARED_DB_TEST") != "I_UNDERSTAND":
        pytest.skip("Explicit concurrency test opt-in required")

    parsed = make_url(database_url)

    if parsed.get_backend_name() != "postgresql":
        pytest.fail("PostgreSQL is required")

    if not parsed.database or not parsed.host:
        pytest.fail("A valid database host and name are required")

    real_url = os.getenv("OPSPILOT_REAL_DATABASE_URL")

    if real_url:
        real = make_url(real_url)
        if (
            parsed.host,
            parsed.port,
            parsed.database,
            parsed.username,
        ) == (
            real.host,
            real.port,
            real.database,
            real.username,
        ):
            pytest.fail("Refusing to run against the real database")

    asyncio.run(_run_concurrency_test(database_url))


async def _run_concurrency_test(database_url: str) -> None:
    engine = create_async_engine(
        database_url,
        pool_size=5,
        max_overflow=0,
        pool_pre_ping=True,
        connect_args={"connect_timeout": 10},
    )

    factory = async_sessionmaker(
        engine,
        expire_on_commit=False,
    )

    organization_id = uuid.uuid4()
    reviewer_id = uuid.uuid4()
    customer_id = uuid.uuid4()
    incident_id = uuid.uuid4()
    order_id = uuid.uuid4()
    source_id = uuid.uuid4()
    approval_id = uuid.uuid4()

    unique_key = uuid.uuid4().hex
    now = datetime.now(UTC)

    async def execute_once():
        async with factory() as session:
            return await execute_approved_refund(
                session=session,
                organization_id=organization_id,
                incident_id=incident_id,
                approval_request_id=approval_id,
                customer_id=customer_id,
            )

    try:
        async with factory() as session:
            session.add(
                Organization(
                    id=organization_id,
                    name="Refund Concurrency Test",
                    slug=f"refund-concurrency-{unique_key}",
                )
            )

            session.add(
                User(
                    id=reviewer_id,
                    email=f"refund-{unique_key}@example.com",
                    full_name="Synthetic Refund Reviewer",
                    password_hash="not-a-real-login",
                )
            )

            await session.flush()

            session.add(
                Customer(
                    id=customer_id,
                    organization_id=organization_id,
                    external_customer_id=f"CUST-{unique_key}",
                    full_name="Synthetic Customer",
                )
            )

            await session.flush()

            session.add(
                Incident(
                    id=incident_id,
                    organization_id=organization_id,
                    created_by_user_id=reviewer_id,
                    subject_customer_id=customer_id,
                    title="Concurrent refund retry test",
                    description="Two workers retry one approved refund.",
                    status=IncidentStatus.AWAITING_APPROVAL,
                )
            )

            session.add(
                OperationalOrder(
                    id=order_id,
                    organization_id=organization_id,
                    customer_id=customer_id,
                    external_order_id=f"ORD-{unique_key}",
                    product_name="Synthetic Product",
                    total_amount=Decimal("100.00"),
                    currency="USD",
                    status=OrderStatus.PAID,
                    ordered_at=now,
                )
            )

            await session.flush()

            session.add(
                PaymentTransaction(
                    id=source_id,
                    organization_id=organization_id,
                    order_id=order_id,
                    external_transaction_id=f"CHARGE-{unique_key}",
                    provider="synthetic",
                    transaction_type=PaymentTransactionType.CHARGE,
                    amount=Decimal("100.00"),
                    currency="USD",
                    status=PaymentTransactionStatus.SUCCEEDED,
                    processed_at=now,
                )
            )

            session.add(
                ApprovalRequest(
                    id=approval_id,
                    organization_id=organization_id,
                    incident_id=incident_id,
                    workflow_thread_id=f"refund-test-{unique_key}",
                    action_type=ApprovalActionType.REFUND_TRANSACTION,
                    action_payload={
                        "external_transaction_id": f"CHARGE-{unique_key}",
                        "amount": "100.00",
                        "currency": "USD",
                    },
                    reason="Verified synthetic duplicate charge",
                    status=ApprovalStatus.APPROVED,
                    decided_by_user_id=reviewer_id,
                    decided_at=now,
                )
            )

            await session.commit()

        # Both workers race to execute the SAME approval.
        start = asyncio.Event()

        async def worker():
            await start.wait()
            return await execute_once()

        first_task = asyncio.create_task(worker())
        second_task = asyncio.create_task(worker())

        start.set()

        first, second = await asyncio.wait_for(
            asyncio.gather(first_task, second_task),
            timeout=45,
        )

        assert sorted([first.already_executed, second.already_executed]) == [False, True]

        assert first.refund_transaction_id == second.refund_transaction_id
        assert first.source_transaction_id == f"CHARGE-{unique_key}"
        assert second.source_transaction_id == f"CHARGE-{unique_key}"

        async with factory() as session:
            refund_count = await session.scalar(
                select(func.count())
                .select_from(PaymentTransaction)
                .where(
                    PaymentTransaction.organization_id == organization_id,
                    PaymentTransaction.source_transaction_id == source_id,
                    PaymentTransaction.transaction_type == PaymentTransactionType.REFUND,
                )
            )

            source = await session.get(PaymentTransaction, source_id)
            approval = await session.get(ApprovalRequest, approval_id)

            assert refund_count == 1
            assert source is not None
            assert source.status == PaymentTransactionStatus.REFUNDED
            assert approval is not None
            assert approval.status == ApprovalStatus.EXECUTED
            assert approval.executed_at is not None
            assert approval.decided_by_user_id == reviewer_id

        # Simulate a lost worker response and a later retry.
        retry = await execute_once()

        assert retry.already_executed is True
        assert retry.refund_transaction_id == first.refund_transaction_id

        async with factory() as session:
            final_count = await session.scalar(
                select(func.count())
                .select_from(PaymentTransaction)
                .where(
                    PaymentTransaction.organization_id == organization_id,
                    PaymentTransaction.source_transaction_id == source_id,
                    PaymentTransaction.transaction_type == PaymentTransactionType.REFUND,
                )
            )

            assert final_count == 1

    finally:
        try:
            # Financial FKs now use RESTRICT.
            # Clean child records up before their parents.
            async with factory() as session:
                await session.execute(
                    delete(PaymentTransaction).where(
                        PaymentTransaction.organization_id == organization_id,
                        PaymentTransaction.transaction_type == PaymentTransactionType.REFUND,
                    )
                )

                await session.execute(
                    delete(PaymentTransaction).where(
                        PaymentTransaction.organization_id == organization_id,
                        PaymentTransaction.id == source_id,
                    )
                )

                await session.execute(
                    delete(ApprovalRequest).where(
                        ApprovalRequest.id == approval_id,
                        ApprovalRequest.organization_id == organization_id,
                    )
                )

                await session.execute(
                    delete(OperationalOrder).where(
                        OperationalOrder.id == order_id,
                        OperationalOrder.organization_id == organization_id,
                    )
                )

                await session.execute(
                    delete(Incident).where(
                        Incident.id == incident_id,
                        Incident.organization_id == organization_id,
                    )
                )

                await session.execute(
                    delete(Customer).where(
                        Customer.id == customer_id,
                        Customer.organization_id == organization_id,
                    )
                )

                await session.execute(
                    delete(Organization).where(
                        Organization.id == organization_id,
                    )
                )

                await session.execute(
                    delete(User).where(
                        User.id == reviewer_id,
                    )
                )

                await session.commit()
        finally:
            await engine.dispose()
