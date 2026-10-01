import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import delete, select

from ops_pilot.db.session import (
    async_session_factory,
)
from ops_pilot.models.approval import (
    ApprovalRequest,
    ApprovalStatus,
)
from ops_pilot.models.customer import Customer
from ops_pilot.models.incident import (
    Incident,
    IncidentStatus,
)
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


async def main() -> None:
    marker = uuid.uuid4().hex[:8]

    customer_id: uuid.UUID | None = None
    incident_id: uuid.UUID | None = None

    async with async_session_factory() as session:
        membership_result = await session.execute(select(Membership).limit(1))

        membership = membership_result.scalar_one_or_none()

        if membership is None:
            raise RuntimeError("No membership exists. Create/login a user first.")

        organization_id = membership.organization_id

        user_id = membership.user_id

        customer = Customer(
            organization_id=organization_id,
            external_customer_id=(f"HITL-REJECT-CUSTOMER-{marker}"),
            email=(f"hitl-reject-{marker}@example.com"),
            full_name=("HITL Rejection Test Customer"),
        )

        session.add(customer)
        await session.flush()

        customer_id = customer.id

        order = OperationalOrder(
            organization_id=organization_id,
            customer_id=customer.id,
            external_order_id=(f"ORD-HITL-REJECT-{marker}"),
            product_name="Wireless Headphones",
            total_amount=Decimal("12000.00"),
            currency="PKR",
            status=OrderStatus.PAID,
            ordered_at=(datetime.now(UTC) - timedelta(minutes=10)),
        )

        session.add(order)
        await session.flush()

        original_charge = PaymentTransaction(
            organization_id=organization_id,
            order_id=order.id,
            external_transaction_id=(f"TXN-HITL-REJECT-A-{marker}"),
            provider="stripe",
            transaction_type=(PaymentTransactionType.CHARGE),
            amount=Decimal("12000.00"),
            currency="PKR",
            status=(PaymentTransactionStatus.SUCCEEDED),
            processed_at=(datetime.now(UTC) - timedelta(minutes=9)),
        )

        duplicate_charge = PaymentTransaction(
            organization_id=organization_id,
            order_id=order.id,
            external_transaction_id=(f"TXN-HITL-REJECT-B-{marker}"),
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

        await session.flush()

        incident = Incident(
            organization_id=organization_id,
            created_by_user_id=user_id,
            subject_customer_id=customer.id,
            title=("Confirmed duplicate payment requires refund approval"),
            description=(
                "The customer was charged twice "
                "for the same Wireless Headphones "
                "order. "
                f"{duplicate_charge.external_transaction_id} "
                "has already been confirmed by "
                "support as the accidental duplicate "
                "charge. Refund exactly that "
                "transaction after human approval."
            ),
        )

        session.add(incident)

        await session.commit()

        incident_id = incident.id

        print("\n=== SEEDED HITL REJECTION DATA ===")

        print(
            "Duplicate transaction:",
            duplicate_charge.external_transaction_id,
        )

        try:
            result = await investigate_incident(
                session=session,
                organization_id=organization_id,
                incident_id=incident.id,
            )

            if not result.approval_required:
                raise RuntimeError("Expected approval requirement but no approval was proposed.")

            if result.approval_request_id is None:
                raise RuntimeError("Approval request was not created.")

            approval_result = await session.execute(
                select(ApprovalRequest).where(ApprovalRequest.id == result.approval_request_id)
            )

            approval = approval_result.scalar_one()

            if approval.status != ApprovalStatus.PENDING:
                raise RuntimeError("Approval is not pending.")

            print("\n=== WORKFLOW PAUSED ===")
            print(
                "Approval:",
                approval.id,
            )

            await decide_and_resume_approval(
                session=session,
                organization_id=organization_id,
                incident_id=incident.id,
                approval_request_id=approval.id,
                decided_by_user_id=user_id,
                payload=ApprovalDecisionRequest(
                    approved=False,
                    comment=("Reject refund for live HITL rejection test."),
                ),
            )

            await session.refresh(approval)
            await session.refresh(incident)
            await session.refresh(duplicate_charge)

            if approval.status != ApprovalStatus.REJECTED:
                raise RuntimeError("Approval was not rejected.")

            if incident.status != IncidentStatus.INVESTIGATING:
                raise RuntimeError("Rejected incident did not return to investigating.")

            if duplicate_charge.status != PaymentTransactionStatus.SUCCEEDED:
                raise RuntimeError("Rejected charge status changed unexpectedly.")

            refund_result = await session.execute(
                select(PaymentTransaction).where(
                    PaymentTransaction.source_transaction_id == duplicate_charge.id,
                    PaymentTransaction.transaction_type == PaymentTransactionType.REFUND,
                )
            )

            refund = refund_result.scalar_one_or_none()

            if refund is not None:
                raise RuntimeError("Refund was created after rejection.")

            print("\n=== REJECTION VERIFIED ===")

            print(
                "Approval status:",
                approval.status,
            )

            print(
                "Incident status:",
                incident.status,
            )

            print(
                "Charge status:",
                duplicate_charge.status,
            )

            print(
                "Refund created:",
                False,
            )

            print("\n=== PHASE 8 HITL REJECTION LIVE TEST PASSED ===")

        finally:
            if incident_id is not None:
                await session.execute(delete(Incident).where(Incident.id == incident_id))

            if customer_id is not None:
                await session.execute(delete(Customer).where(Customer.id == customer_id))

            await session.commit()

            print("\nTemporary rejection test records cleaned up.")


if __name__ == "__main__":
    asyncio.run(main())
