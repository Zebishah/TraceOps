import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from qdrant_client import models
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ops_pilot.core.config import get_settings
from ops_pilot.db.session import async_session_factory
from ops_pilot.models.customer import Customer
from ops_pilot.models.incident import Incident
from ops_pilot.models.incident_memory import IncidentMemory
from ops_pilot.models.membership import Membership
from ops_pilot.models.order import (
    OperationalOrder,
    OrderStatus,
)
from ops_pilot.models.payment_transaction import (
    PaymentTransaction,
    PaymentTransactionStatus,
    PaymentTransactionType,
)
from ops_pilot.schemas.approvals import (
    ApprovalDecisionRequest,
)
from ops_pilot.services.approval_workflow import (
    decide_and_resume_approval,
)
from ops_pilot.services.incident_investigation import (
    investigate_incident,
)
from ops_pilot.vectorstore.qdrant import (
    get_qdrant_client,
)


async def seed_duplicate_incident(
    *,
    session: AsyncSession,
    organization_id: uuid.UUID,
    user_id: uuid.UUID,
    customer_id: uuid.UUID,
    marker: str,
    suffix: str,
) -> uuid.UUID:
    order = OperationalOrder(
        organization_id=organization_id,
        customer_id=customer_id,
        external_order_id=(f"ORD-MEMORY-{suffix}-{marker}"),
        product_name="Wireless Headphones",
        total_amount=Decimal("12000.00"),
        currency="PKR",
        status=OrderStatus.PAID,
        ordered_at=(datetime.now(UTC) - timedelta(minutes=10)),
    )

    session.add(order)

    await session.flush()

    order_id = order.id

    duplicate_external_transaction_id = f"TXN-MEMORY-{suffix}-B-{marker}"

    original_charge = PaymentTransaction(
        organization_id=organization_id,
        order_id=order_id,
        external_transaction_id=(f"TXN-MEMORY-{suffix}-A-{marker}"),
        provider="stripe",
        transaction_type=(PaymentTransactionType.CHARGE),
        amount=Decimal("12000.00"),
        currency="PKR",
        status=(PaymentTransactionStatus.SUCCEEDED),
        processed_at=(datetime.now(UTC) - timedelta(minutes=9)),
    )

    duplicate_charge = PaymentTransaction(
        organization_id=organization_id,
        order_id=order_id,
        external_transaction_id=(duplicate_external_transaction_id),
        provider="stripe",
        transaction_type=(PaymentTransactionType.CHARGE),
        amount=Decimal("12000.00"),
        currency="PKR",
        status=(PaymentTransactionStatus.SUCCEEDED),
        processed_at=(datetime.now(UTC) - timedelta(minutes=8)),
    )

    session.add_all(
        [
            original_charge,
            duplicate_charge,
        ]
    )

    incident = Incident(
        organization_id=organization_id,
        created_by_user_id=user_id,
        subject_customer_id=customer_id,
        title=(f"Confirmed duplicate payment requires refund approval {marker}"),
        description=(
            "The customer was charged twice for the same "
            "Wireless Headphones order. "
            f"{duplicate_external_transaction_id} "
            "has already been confirmed by support as "
            "the accidental duplicate charge. "
            "Refund exactly that transaction after "
            "human approval. "
            f"Test marker: {marker}."
        ),
    )

    session.add(incident)

    await session.flush()

    # Copy primitive ID BEFORE commit/workflow boundaries.
    incident_id = incident.id

    await session.commit()

    return incident_id


async def main() -> None:
    marker = uuid.uuid4().hex[:8]

    customer_id: uuid.UUID | None = None
    incident_a_id: uuid.UUID | None = None
    incident_b_id: uuid.UUID | None = None
    memory_id: uuid.UUID | None = None

    async with async_session_factory() as session:
        membership_result = await session.execute(select(Membership).limit(1))

        membership = membership_result.scalar_one_or_none()

        if membership is None:
            raise RuntimeError("No membership exists. Create/login a user first.")

        # Copy primitives immediately.
        organization_id = membership.organization_id

        user_id = membership.user_id

        customer = Customer(
            organization_id=organization_id,
            external_customer_id=(f"MEMORY-CUSTOMER-{marker}"),
            email=(f"memory-{marker}@example.com"),
            full_name=("Incident Memory Test Customer"),
        )

        session.add(customer)

        await session.flush()

        # Copy primitive ID before commit.
        customer_id = customer.id

        await session.commit()

        try:
            # ==========================================
            # INCIDENT A
            # Resolve it and create durable memory.
            # ==========================================

            incident_a_id = await seed_duplicate_incident(
                session=session,
                organization_id=organization_id,
                user_id=user_id,
                customer_id=customer_id,
                marker=marker,
                suffix="A",
            )

            print("\n=== INCIDENT A CREATED ===")

            print(
                "Incident A:",
                incident_a_id,
            )

            result_a = await investigate_incident(
                session=session,
                organization_id=organization_id,
                incident_id=incident_a_id,
            )

            if not result_a.approval_required:
                raise RuntimeError("Incident A did not pause for approval.")

            approval_request_id = result_a.approval_request_id

            if approval_request_id is None:
                raise RuntimeError("Incident A approval request was not created.")

            await decide_and_resume_approval(
                session=session,
                organization_id=organization_id,
                incident_id=incident_a_id,
                approval_request_id=(approval_request_id),
                decided_by_user_id=user_id,
                payload=ApprovalDecisionRequest(
                    approved=True,
                    comment=("Approve duplicate refund for memory smoke test."),
                ),
            )

            # Query again using primitive UUID.
            memory_result = await session.execute(
                select(IncidentMemory).where(
                    IncidentMemory.organization_id == organization_id,
                    IncidentMemory.incident_id == incident_a_id,
                )
            )

            memory = memory_result.scalar_one_or_none()

            if memory is None:
                raise RuntimeError("Incident A resolved but memory was not created.")

            # Copy ALL values needed later before
            # another workflow can rollback session.
            memory_id = memory.id
            memory_summary = memory.summary
            memory_resolution = memory.resolution

            print("\n=== INCIDENT A MEMORY CREATED ===")

            print(
                "Memory ID:",
                memory_id,
            )

            print(
                "Summary:",
                memory_summary,
            )

            print(
                "Resolution:",
                memory_resolution,
            )

            # ==========================================
            # INCIDENT B
            # It should retrieve Incident A memory.
            # ==========================================

            incident_b_id = await seed_duplicate_incident(
                session=session,
                organization_id=organization_id,
                user_id=user_id,
                customer_id=customer_id,
                marker=marker,
                suffix="B",
            )

            print("\n=== INCIDENT B CREATED ===")

            print(
                "Incident B:",
                incident_b_id,
            )

            result_b = await investigate_incident(
                session=session,
                organization_id=organization_id,
                incident_id=incident_b_id,
            )

            print("\n=== INCIDENT B RETRIEVED MEMORIES ===")

            for retrieved_memory in result_b.similar_memories:
                print(
                    "Memory:",
                    retrieved_memory.memory_id,
                )

                print(
                    "Source incident:",
                    retrieved_memory.incident_id,
                )

                print(
                    "Score:",
                    retrieved_memory.vector_score,
                )

                print(
                    "Summary:",
                    retrieved_memory.summary,
                )

            matched_memory = next(
                (
                    retrieved_memory
                    for retrieved_memory in result_b.similar_memories
                    if retrieved_memory.incident_id == incident_a_id
                ),
                None,
            )

            if matched_memory is None:
                raise RuntimeError("Incident B did not retrieve Incident A memory.")

            if matched_memory.memory_id != memory_id:
                raise RuntimeError("Retrieved memory ID does not match Incident A memory.")

            print("\n=== PHASE 9 MEMORY LIVE TEST PASSED ===")

        finally:
            # Always reset session state before cleanup.
            await session.rollback()

            # If memory was created but an exception
            # happened before we copied its ID,
            # recover the ID using primitive incident ID.
            if memory_id is None and incident_a_id is not None:
                recovery_result = await session.execute(
                    select(IncidentMemory.id).where(
                        IncidentMemory.organization_id == organization_id,
                        IncidentMemory.incident_id == incident_a_id,
                    )
                )

                memory_id = recovery_result.scalar_one_or_none()

                await session.rollback()

            # Remove memory vector from Qdrant.
            if memory_id is not None and incident_a_id is not None:
                settings = get_settings()

                client = get_qdrant_client()

                await client.delete(
                    collection_name=(settings.qdrant_memory_collection_name),
                    points_selector=models.FilterSelector(
                        filter=models.Filter(
                            must=[
                                models.FieldCondition(
                                    key="organization_id",
                                    match=models.MatchValue(
                                        value=str(
                                            organization_id,
                                        ),
                                    ),
                                ),
                                models.FieldCondition(
                                    key="incident_id",
                                    match=models.MatchValue(
                                        value=str(
                                            incident_a_id,
                                        ),
                                    ),
                                ),
                            ]
                        )
                    ),
                    wait=True,
                )

            # Only primitive UUIDs are used here.
            if incident_b_id is not None:
                await session.execute(delete(Incident).where(Incident.id == incident_b_id))

            if incident_a_id is not None:
                await session.execute(delete(Incident).where(Incident.id == incident_a_id))

            if customer_id is not None:
                await session.execute(delete(Customer).where(Customer.id == customer_id))

            await session.commit()

            print("\nTemporary Phase 9 memory test records cleaned up.")


if __name__ == "__main__":
    asyncio.run(main())
