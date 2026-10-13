import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ops_pilot.models.customer import Customer
from ops_pilot.schemas.incident_memories import (
    IncidentMemoryRetrievalResult,
)
from ops_pilot.schemas.mcp_operational import MCPCustomer
from ops_pilot.services.incident_memory_retrieval import (
    retrieve_similar_incident_memories,
)
from ops_pilot.services.mcp_incidents import (
    get_incident_detail,
)
from ops_pilot.services.operational_data import (
    get_operational_order,
    get_payment_transaction,
    list_customer_orders,
    list_order_payments,
)
from ops_pilot.tools.schemas import (
    OperationalOrderData,
    PaymentTransactionData,
)


async def get_customer(
    *,
    session: AsyncSession,
    organization_id: uuid.UUID,
    customer_id: uuid.UUID,
) -> MCPCustomer | None:
    result = await session.execute(
        select(Customer).where(
            Customer.id == customer_id,
            Customer.organization_id == organization_id,
        )
    )

    customer = result.scalar_one_or_none()

    if customer is None:
        return None

    return MCPCustomer.model_validate(
        customer,
    )


async def list_customer_orders_for_mcp(
    *,
    session: AsyncSession,
    organization_id: uuid.UUID,
    customer_id: uuid.UUID,
    limit: int,
) -> list[OperationalOrderData]:
    orders = await list_customer_orders(
        session=session,
        organization_id=organization_id,
        customer_id=customer_id,
        limit=limit,
    )

    return [
        OperationalOrderData.model_validate(
            order,
        )
        for order in orders
    ]


async def get_order_for_mcp(
    *,
    session: AsyncSession,
    organization_id: uuid.UUID,
    customer_id: uuid.UUID,
    external_order_id: str,
) -> OperationalOrderData | None:
    order = await get_operational_order(
        session=session,
        organization_id=organization_id,
        customer_id=customer_id,
        external_order_id=external_order_id,
    )

    if order is None:
        return None

    return OperationalOrderData.model_validate(
        order,
    )


async def list_order_payments_for_mcp(
    *,
    session: AsyncSession,
    organization_id: uuid.UUID,
    customer_id: uuid.UUID,
    external_order_id: str,
) -> list[PaymentTransactionData]:
    payments = await list_order_payments(
        session=session,
        organization_id=organization_id,
        customer_id=customer_id,
        external_order_id=external_order_id,
    )

    return [
        PaymentTransactionData.model_validate(
            payment,
        )
        for payment in payments
    ]


async def get_payment_transaction_for_mcp(
    *,
    session: AsyncSession,
    organization_id: uuid.UUID,
    customer_id: uuid.UUID,
    external_transaction_id: str,
) -> PaymentTransactionData | None:
    transaction = await get_payment_transaction(
        session=session,
        organization_id=organization_id,
        customer_id=customer_id,
        external_transaction_id=external_transaction_id,
    )

    if transaction is None:
        return None

    return PaymentTransactionData.model_validate(
        transaction,
    )


async def search_incident_memory_for_mcp(
    *,
    session: AsyncSession,
    organization_id: uuid.UUID,
    incident_id: uuid.UUID,
    limit: int,
) -> list[IncidentMemoryRetrievalResult]:
    incident = await get_incident_detail(
        session=session,
        organization_id=organization_id,
        incident_id=incident_id,
    )

    if incident is None:
        return []

    if incident.category is None:
        return []

    return await retrieve_similar_incident_memories(
        session=session,
        organization_id=organization_id,
        current_incident_id=incident.id,
        title=incident.title,
        description=incident.description,
        category=incident.category,
        limit=limit,
    )
