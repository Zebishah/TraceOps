import asyncio
import os
import uuid
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from ops_pilot.models.customer import Customer
from ops_pilot.models.order import OperationalOrder, OrderStatus
from ops_pilot.models.organization import Organization
from ops_pilot.models.payment_transaction import (
    PaymentTransaction,
    PaymentTransactionStatus,
    PaymentTransactionType,
)

CUSTOMER_REF = "CUST-SP-6201"
ORDER_REF = "SP-88420"
PAYMENTS = (
    ("CB-PAY-77101", datetime(2026, 10, 20, 11, 10, 15, tzinfo=UTC)),
    ("CB-PAY-77102", datetime(2026, 10, 20, 11, 12, 5, tzinfo=UTC)),
)


async def main():
    org_id = uuid.UUID(os.environ["TARGET_ORGANIZATION_ID"])
    database_url = os.environ["OPSPILOT_SEED_DATABASE_URL"]

    url = make_url(database_url)
    print(f"Database host: {url.host}")
    print(f"Database name: {url.database}")
    print(f"Target organization: {org_id}")

    if input("Type SEED to continue: ").strip() != "SEED":
        print("Cancelled. Nothing changed.")
        return

    engine = create_async_engine(database_url, pool_pre_ping=True)
    Session = async_sessionmaker(engine, expire_on_commit=False)

    try:
        async with Session() as session:
            async with session.begin():
                org = await session.get(Organization, org_id)
                if org is None:
                    raise RuntimeError("Target organization does not exist")

                print(f"Organization verified: {org.name}")

                customer = (
                    await session.execute(
                        select(Customer).where(
                            Customer.organization_id == org_id,
                            Customer.external_customer_id == CUSTOMER_REF,
                        )
                    )
                ).scalar_one_or_none()

                if customer is None:
                    customer = Customer(
                        id=uuid.uuid4(),
                        organization_id=org_id,
                        external_customer_id=CUSTOMER_REF,
                        full_name="Elena Brooks",
                        email=None,
                    )
                    session.add(customer)
                    await session.flush()

                order = (
                    await session.execute(
                        select(OperationalOrder).where(
                            OperationalOrder.organization_id == org_id,
                            OperationalOrder.external_order_id == ORDER_REF,
                        )
                    )
                ).scalar_one_or_none()

                if order is None:
                    order = OperationalOrder(
                        id=uuid.uuid4(),
                        organization_id=org_id,
                        customer_id=customer.id,
                        external_order_id=ORDER_REF,
                        product_name="Camping lantern",
                        total_amount=Decimal("64.80"),
                        currency="USD",
                        status=OrderStatus.PAID,
                        ordered_at=datetime(
                            2026,
                            10,
                            20,
                            11,
                            9,
                            tzinfo=UTC,
                        ),
                    )
                    session.add(order)
                    await session.flush()
                elif order.customer_id != customer.id:
                    raise RuntimeError("Existing order belongs to another customer")

                for transaction_ref, processed_at in PAYMENTS:
                    existing = (
                        await session.execute(
                            select(PaymentTransaction).where(
                                PaymentTransaction.organization_id == org_id,
                                PaymentTransaction.external_transaction_id == transaction_ref,
                            )
                        )
                    ).scalar_one_or_none()

                    if existing is not None:
                        if (
                            existing.order_id != order.id
                            or existing.amount != Decimal("64.80")
                            or existing.status != PaymentTransactionStatus.SUCCEEDED
                            or existing.transaction_type != PaymentTransactionType.CHARGE
                            or existing.currency != "USD"
                            or existing.provider != "clearbrook_demo"
                            or existing.processed_at != processed_at
                        ):
                            raise RuntimeError(f"Existing transaction conflicts: {transaction_ref}")
                        continue

                    session.add(
                        PaymentTransaction(
                            id=uuid.uuid4(),
                            organization_id=org_id,
                            order_id=order.id,
                            external_transaction_id=transaction_ref,
                            provider="clearbrook_demo",
                            transaction_type=PaymentTransactionType.CHARGE,
                            amount=Decimal("64.80"),
                            currency="USD",
                            status=PaymentTransactionStatus.SUCCEEDED,
                            processed_at=processed_at,
                        )
                    )

                await session.flush()

                print(f"Customer UUID: {customer.id}")
                print(f"Order UUID: {order.id}")
                print("Transactions verified: 2")

        print("SEED SUCCESSFUL")

    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
