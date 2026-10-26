"""Real PostgreSQL + LangGraph crash-window regression.

Uses only a confirmed disposable test database.
No external payment provider calls are made.
"""

import os
import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import delete, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import ops_pilot.services.approval_resume_reconciliation as reconciliation
from ops_pilot.models.approval import (
    ApprovalActionType,
    ApprovalRequest,
    ApprovalStatus,
)
from ops_pilot.models.approval_resume_job import (
    ApprovalResumeJob,
    ApprovalResumeJobStatus,
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
from ops_pilot.schemas.incident_actions import IncidentActionProposal
from ops_pilot.services.approval_resume_recovery import MAX_ATTEMPTS
from ops_pilot.services.refund_execution import execute_approved_refund
from ops_pilot.workflows.incident.checkpointing import (
    open_incident_checkpointer,
)
from ops_pilot.workflows.incident.graph import (
    build_incident_investigation_graph,
)


@pytest.mark.asyncio
async def test_refund_commit_before_checkpoint_stays_quarantined(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database_url = os.getenv("OPSPILOT_TEST_DATABASE_URL")

    if not database_url:
        pytest.skip("Set OPSPILOT_TEST_DATABASE_URL")

    if os.getenv("OPSPILOT_DEDICATED_TEST_DB") != "YES":
        pytest.skip("Requires isolated test database")

    if os.getenv("DATABASE_URL") != database_url:
        pytest.fail("DATABASE_URL must point to the same isolated test database")

    parsed = make_url(database_url)

    if parsed.get_backend_name() != "postgresql":
        pytest.fail("PostgreSQL required")

    engine = create_async_engine(
        database_url,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=0,
    )

    sessions = async_sessionmaker(
        engine,
        expire_on_commit=False,
    )

    monkeypatch.setattr(
        reconciliation,
        "async_session_factory",
        sessions,
    )

    suffix = uuid.uuid4().hex

    organization_id = uuid.uuid4()
    user_id = uuid.uuid4()
    customer_id = uuid.uuid4()
    incident_id = uuid.uuid4()
    order_id = uuid.uuid4()
    source_id = uuid.uuid4()
    approval_id = uuid.uuid4()
    job_id = uuid.uuid4()

    thread_id = f"phase20-crash-{suffix}"
    charge_id = f"PHASE20-CHARGE-{suffix}"
    now = datetime.now(UTC)

    config = {
        "configurable": {
            "thread_id": thread_id,
        }
    }

    try:
        # Create independent synthetic database records.
        async with sessions() as session:
            session.add(
                Organization(
                    id=organization_id,
                    name="Phase20 Crash Test",
                    slug=f"phase20-{suffix}",
                )
            )
            session.add(
                User(
                    id=user_id,
                    email=f"phase20-{suffix}@example.com",
                    full_name="Synthetic Reviewer",
                    password_hash="not-a-login",
                )
            )
            await session.flush()

            session.add(
                Customer(
                    id=customer_id,
                    organization_id=organization_id,
                    external_customer_id=f"CUST-{suffix}",
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
                    title="Simulated crash during refund",
                    description="Isolated synthetic recovery test",
                    status=IncidentStatus.AWAITING_APPROVAL,
                )
            )

            session.add(
                OperationalOrder(
                    id=order_id,
                    organization_id=organization_id,
                    customer_id=customer_id,
                    external_order_id=f"ORDER-{suffix}",
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
                    external_transaction_id=charge_id,
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
                    workflow_thread_id=thread_id,
                    action_type=ApprovalActionType.REFUND_TRANSACTION,
                    action_payload={
                        "external_transaction_id": charge_id,
                        "amount": "100.00",
                        "currency": "USD",
                    },
                    reason="Synthetic duplicate payment",
                    status=ApprovalStatus.APPROVED,
                    decided_by_user_id=user_id,
                    decided_at=now,
                )
            )

            session.add(
                ApprovalResumeJob(
                    id=job_id,
                    organization_id=organization_id,
                    incident_id=incident_id,
                    approval_request_id=approval_id,
                    status=ApprovalResumeJobStatus.FAILED.value,
                    attempts=MAX_ATTEMPTS,
                    last_error="Simulated crash after refund commit",
                )
            )

            await session.commit()

        # Create a REAL LangGraph checkpoint at the approval gate.
        proposal = IncidentActionProposal(
            requires_approval=True,
            action_type=ApprovalActionType.REFUND_TRANSACTION,
            external_transaction_id=charge_id,
            amount=Decimal("100.00"),
            currency="USD",
            reason="Synthetic duplicate payment",
        )

        async with open_incident_checkpointer() as checkpointer:
            graph = build_incident_investigation_graph(
                checkpointer=checkpointer,
            )

            await graph.aupdate_state(
                config,
                {
                    "organization_id": organization_id,
                    "incident_id": incident_id,
                    "workflow_thread_id": thread_id,
                    "approval_request_id": approval_id,
                    "proposed_action": proposal,
                    "subject_customer_id": customer_id,
                },
                as_node="create_approval",
            )

            await graph.ainvoke(
                None,
                config=config,
            )

            checkpoint = await graph.aget_state(config)

            assert any(
                task.name == "approval_gate" and bool(task.interrupts) for task in checkpoint.tasks
            ), "Expected a persisted approval-gate interruption"

        # Simulate the financial step succeeding and committing,
        # while the graph checkpoint remains at the gate.
        async with sessions() as session:
            first = await execute_approved_refund(
                session=session,
                organization_id=organization_id,
                incident_id=incident_id,
                approval_request_id=approval_id,
                customer_id=customer_id,
            )

        assert first.already_executed is False

        # The database now knows the refund executed,
        # but LangGraph has not recorded a terminal checkpoint.
        async with sessions() as session:
            saved = await session.get(ApprovalRequest, approval_id)

            assert saved is not None
            assert saved.status == ApprovalStatus.EXECUTED

        # Reconciliation MUST refuse completion.
        verified = await reconciliation.verify_quarantined_job(
            job_id=job_id,
        )
        assert verified is False

        result = await reconciliation.reconcile_quarantined_jobs()

        assert result.completed == 0

        # Verify the job remains quarantined.
        async with sessions() as session:
            job = await session.get(ApprovalResumeJob, job_id)

            assert job is not None
            assert job.status == ApprovalResumeJobStatus.FAILED.value
            assert job.attempts == MAX_ATTEMPTS

        # A refund-service retry cannot create another refund.
        async with sessions() as session:
            retry = await execute_approved_refund(
                session=session,
                organization_id=organization_id,
                incident_id=incident_id,
                approval_request_id=approval_id,
                customer_id=customer_id,
            )

        assert retry.already_executed is True
        assert retry.refund_transaction_id == first.refund_transaction_id

        async with sessions() as session:
            refund_count = await session.scalar(
                select(func.count())
                .select_from(PaymentTransaction)
                .where(
                    PaymentTransaction.organization_id == organization_id,
                    PaymentTransaction.source_transaction_id == source_id,
                    PaymentTransaction.transaction_type == PaymentTransactionType.REFUND,
                )
            )

            assert refund_count == 1

    finally:
        # Clean up ONLY our synthetic LangGraph thread.
        try:
            async with sessions() as session:
                for table in (
                    "checkpoint_writes",
                    "checkpoint_blobs",
                    "checkpoints",
                ):
                    await session.execute(
                        text(f"DELETE FROM {table} WHERE thread_id = :thread_id"),
                        {"thread_id": thread_id},
                    )
                await session.commit()
        finally:
            try:
                # Foreign keys cascade from the synthetic
                # organization; remove its synthetic user too.
                async with sessions() as session:
                    await session.execute(
                        delete(Organization).where(Organization.id == organization_id)
                    )
                    await session.execute(delete(User).where(User.id == user_id))
                    await session.commit()
            finally:
                await engine.dispose()
