import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select

from ops_pilot.db.session import async_session_factory
from ops_pilot.models.customer import Customer
from ops_pilot.models.incident import Incident
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


async def main() -> None:
    marker = uuid.uuid4().hex[:8]

    async with async_session_factory() as session:
        membership_result = await session.execute(select(Membership).limit(1))

        membership = membership_result.scalar_one_or_none()

        if membership is None:
            raise RuntimeError("No membership exists. Create/login a user first.")

        organization_id = membership.organization_id
        user_id = membership.user_id

        customer = Customer(
            organization_id=organization_id,
            external_customer_id=f"MCP-HITL-CUSTOMER-{marker}",
            email=f"mcp-hitl-{marker}@example.com",
            full_name="MCP HITL Test Customer",
        )

        session.add(customer)
        await session.flush()

        order = OperationalOrder(
            organization_id=organization_id,
            customer_id=customer.id,
            external_order_id=f"ORD-MCP-HITL-{marker}",
            product_name="Wireless Headphones",
            total_amount=Decimal("12000.00"),
            currency="PKR",
            status=OrderStatus.PAID,
            ordered_at=datetime.now(UTC) - timedelta(minutes=10),
        )

        session.add(order)
        await session.flush()

        original_charge = PaymentTransaction(
            organization_id=organization_id,
            order_id=order.id,
            external_transaction_id=f"TXN-MCP-HITL-A-{marker}",
            provider="stripe",
            transaction_type=PaymentTransactionType.CHARGE,
            amount=Decimal("12000.00"),
            currency="PKR",
            status=PaymentTransactionStatus.SUCCEEDED,
            processed_at=datetime.now(UTC) - timedelta(minutes=9),
        )

        duplicate_charge = PaymentTransaction(
            organization_id=organization_id,
            order_id=order.id,
            external_transaction_id=f"TXN-MCP-HITL-B-{marker}",
            provider="stripe",
            transaction_type=PaymentTransactionType.CHARGE,
            amount=Decimal("12000.00"),
            currency="PKR",
            status=PaymentTransactionStatus.SUCCEEDED,
            processed_at=datetime.now(UTC) - timedelta(minutes=8),
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
            subject_customer_id=customer.id,
            title="MCP E2E duplicate payment HITL test",
            description=(
                "Customer was charged twice for the same Wireless Headphones "
                f"order {order.external_order_id}. "
                "Investigate the duplicate charge and recommend the safe resolution. "
                "Do not execute a refund without human approval."
            ),
        )

        session.add(incident)

        await session.commit()

        print()
        print("=== MCP HITL FIXTURE CREATED ===")
        print(f"Organization ID:       {organization_id}")
        print(f"Customer ID:           {customer.id}")
        print(f"Order ID:              {order.external_order_id}")
        print(f"Original transaction:  {original_charge.external_transaction_id}")
        print(f"Duplicate transaction: {duplicate_charge.external_transaction_id}")
        print(f"Incident ID:           {incident.id}")
        print()
        print("No investigation or refund was executed.")


if __name__ == "__main__":
    asyncio.run(main())
