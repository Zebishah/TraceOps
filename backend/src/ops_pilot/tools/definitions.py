from typing import Any

from ops_pilot.tools.schemas import (
    GetOrderInput,
    GetTransactionInput,
    ListCustomerOrdersInput,
    ListOrderPaymentsInput,
)

OPERATIONAL_TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "list_customer_orders",
            "description": (
                "List recent orders belonging to the customer currently "
                "being investigated. Use this when the incident does not "
                "identify a specific order."
            ),
            "parameters": ListCustomerOrdersInput.model_json_schema(),
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_order",
            "description": ("Inspect one specific order belonging to the current customer."),
            "parameters": GetOrderInput.model_json_schema(),
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_order_payments",
            "description": (
                "List payment transactions for one order belonging to the current customer."
            ),
            "parameters": ListOrderPaymentsInput.model_json_schema(),
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_transaction",
            "description": (
                "Inspect one specific payment transaction belonging to the current customer."
            ),
            "parameters": GetTransactionInput.model_json_schema(),
        },
    },
]
