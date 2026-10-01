import json

from ops_pilot.schemas.incident_classification import (
    IncidentCategory,
)
from ops_pilot.tools.schemas import (
    OperationalToolName,
    ToolCallRequest,
    ToolExecutionResult,
)


def _successful_results_for_tool(
    *,
    tool_results: list[ToolExecutionResult],
    tool_name: OperationalToolName,
) -> list[ToolExecutionResult]:
    return [result for result in tool_results if (result.success and result.tool_name == tool_name)]


def _extract_order_ids(
    tool_results: list[ToolExecutionResult],
) -> list[str]:
    order_ids: list[str] = []

    results = _successful_results_for_tool(
        tool_results=tool_results,
        tool_name=(OperationalToolName.LIST_CUSTOMER_ORDERS),
    )

    for result in results:
        try:
            payload = json.loads(result.content)
        except json.JSONDecodeError:
            continue

        if not isinstance(
            payload,
            list,
        ):
            continue

        for item in payload:
            if not isinstance(
                item,
                dict,
            ):
                continue

            order_id = item.get("external_order_id")

            if (
                isinstance(
                    order_id,
                    str,
                )
                and order_id not in order_ids
            ):
                order_ids.append(order_id)

    return order_ids


def tool_call_already_executed(
    *,
    tool_call: ToolCallRequest,
    tool_results: list[ToolExecutionResult],
) -> bool:
    for result in tool_results:
        if not result.success:
            continue

        if result.tool_name != tool_call.tool_name:
            continue

        if result.arguments == tool_call.arguments:
            return True

    return False


def required_operational_tool(
    *,
    category: IncidentCategory,
    tool_results: list[ToolExecutionResult],
) -> ToolCallRequest | None:
    if category != IncidentCategory.PAYMENT:
        return None

    order_listing_done = any(
        result.success and result.tool_name == (OperationalToolName.LIST_CUSTOMER_ORDERS)
        for result in tool_results
    )

    if not order_listing_done:
        return ToolCallRequest(
            call_id=("required-list-customer-orders"),
            tool_name=(OperationalToolName.LIST_CUSTOMER_ORDERS),
            arguments={
                "limit": 10,
            },
        )

    order_ids = _extract_order_ids(tool_results)

    if not order_ids:
        return None

    for order_id in order_ids:
        candidate = ToolCallRequest(
            call_id=(f"required-list-order-payments-{order_id}"),
            tool_name=(OperationalToolName.LIST_ORDER_PAYMENTS),
            arguments={
                "order_id": order_id,
            },
        )

        if not tool_call_already_executed(
            tool_call=candidate,
            tool_results=tool_results,
        ):
            return candidate

    return None
