import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ops_pilot.models.order import OperationalOrder
from ops_pilot.models.payment_transaction import PaymentTransaction


async def list_customer_orders(
    *,
    session: AsyncSession,
    organization_id: uuid.UUID,
    customer_id: uuid.UUID,
    limit: int,
) -> list[OperationalOrder]:
    result = await session.execute(
        select(OperationalOrder)
        .where(
            OperationalOrder.organization_id == organization_id,
            OperationalOrder.customer_id == customer_id,
        )
        .order_by(OperationalOrder.ordered_at.desc())
        .limit(limit)
    )

    return list(result.scalars().all())


async def get_operational_order(
    *,
    session: AsyncSession,
    organization_id: uuid.UUID,
    customer_id: uuid.UUID,
    external_order_id: str,
) -> OperationalOrder | None:
    result = await session.execute(
        select(OperationalOrder).where(
            OperationalOrder.organization_id == organization_id,
            OperationalOrder.customer_id == customer_id,
            OperationalOrder.external_order_id == external_order_id,
        )
    )

    return result.scalar_one_or_none()


async def list_order_payments(
    *,
    session: AsyncSession,
    organization_id: uuid.UUID,
    customer_id: uuid.UUID,
    external_order_id: str,
) -> list[PaymentTransaction]:
    result = await session.execute(
        select(PaymentTransaction)
        .join(
            OperationalOrder,
            PaymentTransaction.order_id == OperationalOrder.id,
        )
        .where(
            PaymentTransaction.organization_id == organization_id,
            OperationalOrder.organization_id == organization_id,
            OperationalOrder.customer_id == customer_id,
            OperationalOrder.external_order_id == external_order_id,
        )
        .order_by(
            PaymentTransaction.processed_at.desc().nullslast(),
            PaymentTransaction.created_at.desc(),
        )
    )

    return list(result.scalars().all())


async def get_payment_transaction(
    *,
    session: AsyncSession,
    organization_id: uuid.UUID,
    customer_id: uuid.UUID,
    external_transaction_id: str,
) -> PaymentTransaction | None:
    result = await session.execute(
        select(PaymentTransaction)
        .join(
            OperationalOrder,
            PaymentTransaction.order_id == OperationalOrder.id,
        )
        .where(
            PaymentTransaction.organization_id == organization_id,
            OperationalOrder.organization_id == organization_id,
            OperationalOrder.customer_id == customer_id,
            PaymentTransaction.external_transaction_id == external_transaction_id,
        )
    )

    return result.scalar_one_or_none()
