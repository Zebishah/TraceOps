import asyncio
import os
import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import (
    async_sessionmaker,
    create_async_engine,
)

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


def test_two_approvals_create_only_one_refund() -> None:
    database_url = os.environ.get("OPSPILOT_INTEGRATION_DATABASE_URL")

    if not database_url:
        pytest.skip("Set OPSPILOT_INTEGRATION_DATABASE_URL to run PostgreSQL integration tests.")

    parsed_url = make_url(database_url)
    database_name = parsed_url.database or ""

    # Shared development database requires explicit opt-in.
    if os.environ.get("OPSPILOT_ALLOW_SHARED_DB_TEST") != "I_UNDERSTAND":
        pytest.skip("Shared database concurrency test requires explicit opt-in.")

    if not database_name:
        pytest.fail("Database name is missing.")

    if parsed_url.get_backend_name() != "postgresql":
        pytest.fail("PostgreSQL is required.")

    asyncio.run(_run_concurrency_test(database_url))


async def _run_concurrency_test(database_url: str) -> None:
    engine = create_async_engine(
        database_url,
        pool_size=5,
        max_overflow=0,
        connect_args={"connect_timeout": 10},
    )

    session_factory = async_sessionmaker(
        engine,
        expire_on_commit=False,
    )

    organization_id = uuid.uuid4()
    user_id = uuid.uuid4()
    customer_id = uuid.uuid4()
    incident_id = uuid.uuid4()
    order_id = uuid.uuid4()
    source_id = uuid.uuid4()
    approval_a_id = uuid.uuid4()
    approval_b_id = uuid.uuid4()

    unique_key = uuid.uuid4().hex
    now = datetime.now(UTC)

    async def execute_one(approval_id: uuid.UUID):
        async with session_factory() as session:
            return await execute_approved_refund(
                session=session,
                organization_id=organization_id,
                incident_id=incident_id,
                approval_request_id=approval_id,
                customer_id=customer_id,
            )

    try:
        # Seed a complete, isolated synthetic scenario.
        async with session_factory() as session:
            session.add(
                Organization(
                    id=organization_id,
                    name="Concurrency Test Organization",
                    slug=f"concurrency-{unique_key}",
                )
            )
            session.add(
                User(
                    id=user_id,
                    email=f"concurrency-{unique_key}@example.com",
                    full_name="Concurrency Test Reviewer",
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
                    created_by_user_id=user_id,
                    subject_customer_id=customer_id,
                    title="Concurrent refund test",
                    description="Two approvals for one charge.",
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
                    provider="stripe",
                    transaction_type=PaymentTransactionType.CHARGE,
                    amount=Decimal("100.00"),
                    currency="USD",
                    status=PaymentTransactionStatus.SUCCEEDED,
                    processed_at=now,
                )
            )

            for approval_id in (approval_a_id, approval_b_id):
                session.add(
                    ApprovalRequest(
                        id=approval_id,
                        organization_id=organization_id,
                        incident_id=incident_id,
                        workflow_thread_id=f"test-{approval_id}",
                        action_type=ApprovalActionType.REFUND_TRANSACTION,
                        action_payload={
                            "external_transaction_id": f"CHARGE-{unique_key}",
                            "amount": "100.00",
                            "currency": "USD",
                        },
                        reason="Synthetic approved refund.",
                        status=ApprovalStatus.APPROVED,
                        decided_by_user_id=user_id,
                        decided_at=now,
                    )
                )

            await session.commit()

        # Both requests begin concurrently in independent sessions.
        start = asyncio.Event()

        async def worker(approval_id: uuid.UUID):
            await start.wait()
            return await execute_one(approval_id)

        task_a = asyncio.create_task(worker(approval_a_id))
        task_b = asyncio.create_task(worker(approval_b_id))

        start.set()

        result_a, result_b = await asyncio.wait_for(
            asyncio.gather(task_a, task_b),
            timeout=20,
        )

        # Exactly one execution creates the refund.
        assert sorted(
            [
                result_a.already_executed,
                result_b.already_executed,
            ]
        ) == [False, True]

        # Both executions must identify the same refund.
        assert result_a.refund_transaction_id == result_b.refund_transaction_id

        async with session_factory() as session:
            refund_count = await session.scalar(
                select(func.count())
                .select_from(PaymentTransaction)
                .where(
                    PaymentTransaction.source_transaction_id == source_id,
                    PaymentTransaction.transaction_type == PaymentTransactionType.REFUND,
                )
            )

            assert refund_count == 1

            source = await session.get(PaymentTransaction, source_id)
            assert source is not None
            assert source.status == PaymentTransactionStatus.REFUNDED

            approval_a = await session.get(ApprovalRequest, approval_a_id)
            approval_b = await session.get(ApprovalRequest, approval_b_id)

            assert approval_a is not None
            assert approval_b is not None
            assert approval_a.status == ApprovalStatus.EXECUTED
            assert approval_b.status == ApprovalStatus.EXECUTED

        # A further retry must still create no extra refund.
        retry_result = await execute_one(approval_a_id)
        assert retry_result.already_executed is True

        async with session_factory() as session:
            final_count = await session.scalar(
                select(func.count())
                .select_from(PaymentTransaction)
                .where(
                    PaymentTransaction.source_transaction_id == source_id,
                    PaymentTransaction.transaction_type == PaymentTransactionType.REFUND,
                )
            )
            assert final_count == 1

    finally:
        # Remove only records created by this test.
        async with session_factory() as session:
            await session.execute(delete(Organization).where(Organization.id == organization_id))
            await session.execute(delete(User).where(User.id == user_id))
            await session.commit()

        await engine.dispose()
