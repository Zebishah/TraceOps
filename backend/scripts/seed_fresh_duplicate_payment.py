import asyncio
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select

from ops_pilot.db.session import async_session_factory
from ops_pilot.models.customer import Customer
from ops_pilot.models.membership import Membership
from ops_pilot.models.order import OperationalOrder, OrderStatus
from ops_pilot.models.payment_transaction import (
    PaymentTransaction,
    PaymentTransactionStatus,
    PaymentTransactionType,
)


async def main() -> None:
    marker = uuid.uuid4().hex[:8]
    target_organization_id = uuid.UUID("d5d2a37c-5538-4783-8f42-a285d8534b7a")
    fingerprint = f"synthetic-card-{marker}"
    async with async_session_factory() as session:
        membership_result = await session.execute(
            select(Membership)
            .where(
                Membership.organization_id == target_organization_id,
            )
            .limit(1)
        )

        membership = membership_result.scalar_one_or_none()

        if membership is None:
            raise RuntimeError("No organization membership exists. Create/login a user first.")

        organization_id = membership.organization_id

        customer = Customer(
            organization_id=organization_id,
            external_customer_id=f"E2E-CUSTOMER-{marker}",
            email=f"e2e-{marker}@example.com",
            full_name="Fresh Duplicate Payment Customer",
        )

        session.add(customer)
        await session.flush()

        order = OperationalOrder(
            organization_id=organization_id,
            customer_id=customer.id,
            external_order_id=f"ORD-E2E-{marker}",
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
            external_transaction_id=(f"TXN-E2E-A-{marker}"),
            provider="stripe",
            transaction_type=(PaymentTransactionType.CHARGE),
            amount=Decimal("12000.00"),
            currency="PKR",
            payment_instrument_fingerprint=fingerprint,
            status=(PaymentTransactionStatus.SUCCEEDED),
            processed_at=(datetime.now(UTC) - timedelta(minutes=9)),
        )

        duplicate_charge = PaymentTransaction(
            organization_id=organization_id,
            order_id=order.id,
            external_transaction_id=(f"TXN-E2E-B-{marker}"),
            provider="stripe",
            transaction_type=(PaymentTransactionType.CHARGE),
            amount=Decimal("12000.00"),
            currency="PKR",
            payment_instrument_fingerprint=fingerprint,
            status=(PaymentTransactionStatus.SUCCEEDED),
            processed_at=(datetime.now(UTC) - timedelta(minutes=8)),
        )

        session.add_all(
            [
                original_charge,
                duplicate_charge,
            ]
        )

        await session.commit()

        print("\n=== FRESH DUPLICATE PAYMENT DATA ===")
        print(f"Organization ID: {organization_id}")
        print(f"Customer ID:     {customer.id}")
        print(f"Order ID:        {order.external_order_id}")
        print(f"Original charge: {original_charge.external_transaction_id}")
        print(f"Duplicate charge: {duplicate_charge.external_transaction_id}")


if __name__ == "__main__":
    asyncio.run(main())
