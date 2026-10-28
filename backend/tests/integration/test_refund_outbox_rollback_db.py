"""D09: A failed outbox insertion must roll back the real refund."""

import os
import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import ops_pilot.services.refund_execution as refund_service
from ops_pilot.models.approval import (
    ApprovalActionType,
    ApprovalRequest,
    ApprovalStatus,
)
from ops_pilot.models.automation_delivery import AutomationDelivery
from ops_pilot.models.customer import Customer
from ops_pilot.models.incident import Incident, IncidentPriority, IncidentStatus
from ops_pilot.models.order import OperationalOrder, OrderStatus
from ops_pilot.models.organization import Organization
from ops_pilot.models.payment_transaction import (
    PaymentTransaction,
    PaymentTransactionStatus,
    PaymentTransactionType,
)
from ops_pilot.models.user import User

TEST_HOST = "ep-bold-sea-b5exs2wm-pooler.c-7.us-east-2.aws.neon.tech"


@pytest.mark.asyncio
async def test_refund_and_outbox_roll_back_together(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    url = os.getenv("OPSPILOT_TEST_DATABASE_URL")

    if not url:
        pytest.skip("Dedicated TEST database URL required")

    if os.getenv("OPSPILOT_DEDICATED_TEST_DB") != "YES":
        pytest.skip("Explicit isolated TEST database confirmation required")

    if os.getenv("DATABASE_URL") != url:
        pytest.fail("DATABASE_URL must equal OPSPILOT_TEST_DATABASE_URL")

    parsed = make_url(url)

    if parsed.get_backend_name() != "postgresql" or parsed.host != TEST_HOST:
        pytest.fail("Refusing to run against an unexpected database")

    engine = create_async_engine(
        url,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=0,
    )

    sessions = async_sessionmaker(
        engine,
        expire_on_commit=False,
    )

    suffix = uuid.uuid4().hex

    organization_id = uuid.uuid4()
    user_id = uuid.uuid4()
    customer_id = uuid.uuid4()
    incident_id = uuid.uuid4()
    order_id = uuid.uuid4()
    source_id = uuid.uuid4()
    approval_id = uuid.uuid4()

    source_external_id = f"ROLLBACK-CHARGE-{suffix}"
    now = datetime.now(UTC)

    try:
        # SETUP: synthetic records in the dedicated TEST database.
        async with sessions() as session:
            session.add(
                Organization(
                    id=organization_id,
                    name="Refund Outbox Rollback Test",
                    slug=f"refund-rollback-{suffix}",
                )
            )

            session.add(
                User(
                    id=user_id,
                    email=f"rollback-{suffix}@example.com",
                    full_name="Synthetic Test Reviewer",
                    password_hash="not-a-login",
                )
            )

            await session.flush()

            session.add(
                Customer(
                    id=customer_id,
                    organization_id=organization_id,
                    external_customer_id=f"CUST-{suffix}",
                    full_name="Synthetic Test Customer",
                )
            )

            await session.flush()

            session.add(
                Incident(
                    id=incident_id,
                    organization_id=organization_id,
                    created_by_user_id=user_id,
                    subject_customer_id=customer_id,
                    title="Synthetic refund rollback",
                    description="Outbox failure injection test",
                    status=IncidentStatus.AWAITING_APPROVAL,
                    category="payment",
                    priority=IncidentPriority.MEDIUM,
                )
            )

            session.add(
                OperationalOrder(
                    id=order_id,
                    organization_id=organization_id,
                    customer_id=customer_id,
                    external_order_id=f"ORDER-{suffix}",
                    product_name="Synthetic Test Product",
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
                    external_transaction_id=source_external_id,
                    provider="stripe",
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
                    workflow_thread_id=f"refund-rollback-{suffix}",
                    action_type=ApprovalActionType.REFUND_TRANSACTION,
                    action_payload={
                        "external_transaction_id": source_external_id,
                        "amount": "100.00",
                        "currency": "USD",
                    },
                    reason="Synthetic approved refund",
                    status=ApprovalStatus.APPROVED,
                    decided_by_user_id=user_id,
                    decided_at=now,
                )
            )

            await session.commit()

        # Allow the actual outbox INSERT, then raise an
        # exception BEFORE the refund transaction commits.
        real_enqueue = refund_service.enqueue_automation_in_session

        async def fail_after_outbox_insert(**kwargs: object) -> None:
            await real_enqueue(**kwargs)
            raise RuntimeError("Injected failure after outbox insert")

        monkeypatch.setattr(
            refund_service,
            "enqueue_automation_in_session",
            fail_after_outbox_insert,
        )

        async with sessions() as session:
            with pytest.raises(
                RuntimeError,
                match="Injected failure after outbox insert",
            ):
                await refund_service.execute_approved_refund(
                    session=session,
                    organization_id=organization_id,
                    incident_id=incident_id,
                    approval_request_id=approval_id,
                    customer_id=customer_id,
                )

        # VERIFY: The whole financial transaction was rolled back.
        async with sessions() as session:
            approval = await session.get(ApprovalRequest, approval_id)
            source = await session.get(PaymentTransaction, source_id)

            assert approval is not None
            assert source is not None

            assert approval.status == ApprovalStatus.APPROVED
            assert approval.executed_at is None
            assert source.status == PaymentTransactionStatus.SUCCEEDED

            refunds_count = await session.scalar(
                select(func.count())
                .select_from(PaymentTransaction)
                .where(
                    PaymentTransaction.organization_id == organization_id,
                    PaymentTransaction.source_transaction_id == source_id,
                    PaymentTransaction.transaction_type == PaymentTransactionType.REFUND,
                )
            )

            outbox_count = await session.scalar(
                select(func.count())
                .select_from(AutomationDelivery)
                .where(
                    AutomationDelivery.organization_id == organization_id,
                    AutomationDelivery.event_type == "incident.customer_recovery",
                )
            )

            assert refunds_count == 0
            assert outbox_count == 0

    finally:
        # Clean up ONLY the isolated synthetic records.
        try:
            async with sessions() as session:
                await session.execute(
                    delete(Organization).where(Organization.id == organization_id)
                )
                await session.execute(delete(User).where(User.id == user_id))
                await session.commit()
        finally:
            await engine.dispose()
