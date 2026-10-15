import json
import logging
import uuid
from time import perf_counter

from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from ops_pilot.tools.operational import (
    execute_get_order,
    execute_get_transaction,
    execute_list_customer_orders,
    execute_list_order_payments,
)
from ops_pilot.tools.schemas import (
    GetOrderInput,
    GetTransactionInput,
    ListCustomerOrdersInput,
    ListOrderPaymentsInput,
    OperationalToolName,
    ToolCallRequest,
    ToolExecutionResult,
)

logger = logging.getLogger(__name__)


async def execute_operational_tool_call(
    *,
    session: AsyncSession,
    organization_id: uuid.UUID,
    customer_id: uuid.UUID,
    tool_call: ToolCallRequest,
) -> ToolExecutionResult:
    metadata = {
        "organization_id": str(organization_id),
        "tool_name": tool_call.tool_name.value,
        "tool_call_id": tool_call.call_id,
    }

    logger.info(
        "operational_tool_started",
        extra=metadata,
    )

    started_at = perf_counter()

    try:
        try:
            if tool_call.tool_name == OperationalToolName.LIST_CUSTOMER_ORDERS:
                result = await execute_list_customer_orders(
                    session=session,
                    organization_id=organization_id,
                    customer_id=customer_id,
                    tool_input=ListCustomerOrdersInput.model_validate(tool_call.arguments),
                )

            elif tool_call.tool_name == OperationalToolName.GET_ORDER:
                result = await execute_get_order(
                    session=session,
                    organization_id=organization_id,
                    customer_id=customer_id,
                    tool_input=GetOrderInput.model_validate(tool_call.arguments),
                )

            elif tool_call.tool_name == OperationalToolName.LIST_ORDER_PAYMENTS:
                result = await execute_list_order_payments(
                    session=session,
                    organization_id=organization_id,
                    customer_id=customer_id,
                    tool_input=ListOrderPaymentsInput.model_validate(tool_call.arguments),
                )

            elif tool_call.tool_name == OperationalToolName.GET_TRANSACTION:
                result = await execute_get_transaction(
                    session=session,
                    organization_id=organization_id,
                    customer_id=customer_id,
                    tool_input=GetTransactionInput.model_validate(tool_call.arguments),
                )

            else:
                raise RuntimeError("Unsupported operational tool")

        except ValidationError:
            result = ToolExecutionResult(
                call_id=tool_call.call_id,
                tool_name=tool_call.tool_name,
                arguments=dict(tool_call.arguments),
                success=False,
                content=json.dumps(
                    {
                        "error": ("invalid_tool_arguments"),
                    }
                ),
            )

        result = result.model_copy(
            update={
                "call_id": tool_call.call_id,
                "arguments": dict(tool_call.arguments),
            }
        )

    except Exception:
        duration_ms = (perf_counter() - started_at) * 1000

        logger.exception(
            "operational_tool_failed",
            extra={
                **metadata,
                "duration_ms": round(
                    duration_ms,
                    2,
                ),
            },
        )

        raise

    duration_ms = (perf_counter() - started_at) * 1000

    logger.info(
        "operational_tool_finished",
        extra={
            **metadata,
            "success": result.success,
            "duration_ms": round(
                duration_ms,
                2,
            ),
        },
    )

    return result
