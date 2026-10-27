"""Real PostgreSQL + LangGraph approved-refund integration.

Uses only a confirmed disposable test database.
No external payment provider calls are made.
"""

import os
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import delete, func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import ops_pilot.services.approval_resume_processor as processor
import ops_pilot.services.approval_resume_recovery as recovery
import ops_pilot.workflows.incident.nodes as nodes
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
from ops_pilot.models.incident import Incident, IncidentPriority, IncidentStatus
from ops_pilot.models.order import OperationalOrder, OrderStatus
from ops_pilot.models.organization import Organization
from ops_pilot.models.payment_transaction import (
    PaymentTransaction,
    PaymentTransactionStatus,
    PaymentTransactionType,
)
from ops_pilot.models.user import User
from ops_pilot.schemas.incident_actions import IncidentActionProposal
from ops_pilot.schemas.incident_classification import IncidentCategory
from ops_pilot.workflows.incident.checkpointing import (
    open_incident_checkpointer,
)
from ops_pilot.workflows.incident.graph import (
    build_incident_investigation_graph,
)


@pytest.mark.asyncio
async def test_approved_refund_completes_through_real_worker(
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
        processor,
        "async_session_factory",
        sessions,
    )

    monkeypatch.setattr(recovery, "async_session_factory", sessions)

    # Disable only nonfinancial integrations.
    # Real refund execution and verification remain active.
    monkeypatch.setattr(
        nodes,
        "generate_and_store_incident_memory",
        AsyncMock(side_effect=RuntimeError("Memory disabled in test")),
    )
    monkeypatch.setattr(
        nodes,
        "dispatch_incident_resolved_automation",
        AsyncMock(return_value=None),
    )
    monkeypatch.setattr(
        nodes,
        "dispatch_customer_recovery_automation",
        AsyncMock(return_value=None),
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

    thread_id = f"phase20-approved-e2e-{suffix}"
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
                    status=ApprovalResumeJobStatus.PENDING.value,
                    attempts=0,
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
                    "title": "Synthetic approved refund",
                    "description": "Approved refund integration test",
                    "category": IncidentCategory.PAYMENT,
                    "priority": IncidentPriority.MEDIUM,
                    "analysis": "Synthetic duplicate charge confirmed",
                    "recommended_action": "Refund the duplicate charge",
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

        # Process the genuine approval-resume worker.
        result = await processor.run_approval_resume_sweep()

        assert result.claimed == 1
        assert result.completed == 1
        assert result.failed == 0

        async with sessions() as session:
            approval = await session.get(ApprovalRequest, approval_id)
            incident = await session.get(Incident, incident_id)
            job = await session.get(ApprovalResumeJob, job_id)
            source = await session.get(PaymentTransaction, source_id)

            assert approval is not None
            assert incident is not None
            assert job is not None
            assert source is not None

            # Human approval was executed.
            assert approval.status == ApprovalStatus.EXECUTED
            assert approval.executed_at is not None

            # Incident was resolved after simulated refund verification.
            assert incident.status == IncidentStatus.RESOLVED

            # F08: Verify complete resolution audit metadata.
            assert incident.resolved_at is not None
            assert incident.resolved_by_user_id == user_id
            assert incident.resolution_reason is not None

            # The resolution must clearly describe an internal
            # simulated refund, not a real provider refund.
            assert "internal refund ledger" in incident.resolution_reason.lower()
            assert "no external payment provider refund" in incident.resolution_reason.lower()

            # Original synthetic charge was updated.
            assert source.status == PaymentTransactionStatus.REFUNDED

            assert job.status == ApprovalResumeJobStatus.COMPLETED.value
            assert job.completed_at is not None
            assert job.lease_token is None

            refunds = (
                await session.scalars(
                    select(PaymentTransaction).where(
                        PaymentTransaction.organization_id == organization_id,
                        PaymentTransaction.source_transaction_id == source_id,
                        PaymentTransaction.transaction_type == PaymentTransactionType.REFUND,
                    )
                )
            ).all()

            assert len(refunds) == 1
            assert refunds[0].status == PaymentTransactionStatus.SUCCEEDED
            assert refunds[0].amount == Decimal("100.00")
            assert refunds[0].currency == "USD"
            assert refunds[0].order_id == order_id

            await session.rollback()

        async with open_incident_checkpointer() as checkpointer:
            graph = build_incident_investigation_graph(
                checkpointer=checkpointer,
            )
            final_checkpoint = await graph.aget_state(config)

            assert not final_checkpoint.next
            assert not final_checkpoint.tasks
            assert final_checkpoint.values["refund_verified"] is True

        # A second sweep must not reclaim this completed job.
        again = await processor.run_approval_resume_sweep()

        assert again.claimed == 0
        assert again.completed == 0

        async with sessions() as session:
            count = await session.scalar(
                select(func.count())
                .select_from(PaymentTransaction)
                .where(
                    PaymentTransaction.organization_id == organization_id,
                    PaymentTransaction.source_transaction_id == source_id,
                    PaymentTransaction.transaction_type == PaymentTransactionType.REFUND,
                )
            )
            assert count == 1
            await session.rollback()

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
