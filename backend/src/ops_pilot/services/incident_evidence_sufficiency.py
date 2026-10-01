from ops_pilot.schemas.incident_classification import (
    IncidentCategory,
)
from ops_pilot.tools.schemas import (
    OperationalToolName,
    ToolExecutionResult,
)


def has_required_operational_evidence(
    *,
    category: IncidentCategory,
    tool_results: list[ToolExecutionResult],
) -> bool:
    if category != IncidentCategory.PAYMENT:
        return True

    has_orders = any(
        result.success and result.tool_name == (OperationalToolName.LIST_CUSTOMER_ORDERS)
        for result in tool_results
    )

    has_payments = any(
        result.success and result.tool_name == (OperationalToolName.LIST_ORDER_PAYMENTS)
        for result in tool_results
    )

    return has_orders and has_payments
