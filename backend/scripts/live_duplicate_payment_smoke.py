import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import delete, select

from ops_pilot.db.session import async_session_factory
from ops_pilot.models.customer import Customer
from ops_pilot.models.incident import Incident
from ops_pilot.models.membership import Membership
from ops_pilot.models.order import OperationalOrder, OrderStatus
from ops_pilot.models.payment_transaction import (
    PaymentTransaction,
    PaymentTransactionStatus,
    PaymentTransactionType,
)
from ops_pilot.services.incident_investigation import investigate_incident
from ops_pilot.tools.schemas import OperationalToolName


async def main() -> None:
    marker = uuid.uuid4().hex[:8]

    customer_id: uuid.UUID | None = None
    incident_id: uuid.UUID | None = None

    async with async_session_factory() as session:
        membership_result = await session.execute(select(Membership).limit(1))
        membership = membership_result.scalar_one_or_none()

        if membership is None:
            raise RuntimeError("No organization membership exists. Create/login a user first.")

        organization_id = membership.organization_id
        user_id = membership.user_id

        customer = Customer(
            organization_id=organization_id,
            external_customer_id=f"E2E-CUSTOMER-{marker}",
            email=f"e2e-{marker}@example.com",
            full_name="E2E Duplicate Payment Customer",
        )

        session.add(customer)
        await session.flush()

        customer_id = customer.id

        order = OperationalOrder(
            organization_id=organization_id,
            customer_id=customer.id,
            external_order_id=f"ORD-E2E-{marker}",
            product_name="Wireless Headphones",
            total_amount=Decimal("12000.00"),
            currency="PKR",
            status=OrderStatus.PAID,
            ordered_at=datetime.now(UTC) - timedelta(minutes=10),
        )

        session.add(order)
        await session.flush()

        first_charge = PaymentTransaction(
            organization_id=organization_id,
            order_id=order.id,
            external_transaction_id=f"TXN-E2E-A-{marker}",
            provider="stripe",
            transaction_type=PaymentTransactionType.CHARGE,
            amount=Decimal("12000.00"),
            currency="PKR",
            status=PaymentTransactionStatus.SUCCEEDED,
            processed_at=datetime.now(UTC) - timedelta(minutes=9),
        )

        second_charge = PaymentTransaction(
            organization_id=organization_id,
            order_id=order.id,
            external_transaction_id=f"TXN-E2E-B-{marker}",
            provider="stripe",
            transaction_type=PaymentTransactionType.CHARGE,
            amount=Decimal("12000.00"),
            currency="PKR",
            status=PaymentTransactionStatus.SUCCEEDED,
            processed_at=datetime.now(UTC) - timedelta(minutes=8),
        )

        session.add_all(
            [
                first_charge,
                second_charge,
            ]
        )

        incident = Incident(
            organization_id=organization_id,
            created_by_user_id=user_id,
            subject_customer_id=customer.id,
            title="Customer charged twice",
            description=(
                "The customer bought Wireless Headphones for PKR 12,000 "
                "and reports being charged twice for the same purchase."
            ),
        )

        session.add(incident)

        await session.commit()

        incident_id = incident.id

        print("\n=== SEEDED TEST DATA ===")
        print(f"Organization: {organization_id}")
        print(f"Customer:     {customer.id}")
        print(f"Order:        {order.external_order_id}")
        print(f"Transaction 1: {first_charge.external_transaction_id}")
        print(f"Transaction 2: {second_charge.external_transaction_id}")

        try:
            result = await investigate_incident(
                session=session,
                organization_id=organization_id,
                incident_id=incident.id,
            )

            print("\n=== INVESTIGATION RESULT ===")
            print(
                result.model_dump_json(
                    indent=2,
                )
            )

            if result.needs_more_information:
                raise RuntimeError("Investigation unexpectedly requested more information.")

            if result.analysis is None:
                raise RuntimeError("Investigation returned no analysis.")

            if result.recommended_action is None:
                raise RuntimeError("Investigation returned no recommendation.")

            tool_names = {tool_result.tool_name for tool_result in result.tool_results}

            if OperationalToolName.LIST_CUSTOMER_ORDERS not in tool_names:
                raise RuntimeError("Agent did not inspect customer orders.")

            if OperationalToolName.LIST_ORDER_PAYMENTS not in tool_names:
                raise RuntimeError("Agent did not inspect order payments.")

            print("\n=== PHASE 7 LIVE TEST PASSED ===")
            print(f"Tool calls executed: {len(result.tool_results)}")

        finally:
            if incident_id is not None:
                await session.execute(delete(Incident).where(Incident.id == incident_id))

            if customer_id is not None:
                await session.execute(delete(Customer).where(Customer.id == customer_id))

            await session.commit()

            print("\nTemporary E2E records cleaned up.")


if __name__ == "__main__":
    asyncio.run(main())
