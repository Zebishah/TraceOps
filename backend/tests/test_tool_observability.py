import logging
import uuid
from typing import Protocol, cast
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

import ops_pilot.tools.executor as executor_module
from ops_pilot.tools.executor import (
    execute_operational_tool_call,
)
from ops_pilot.tools.schemas import (
    OperationalToolName,
    ToolCallRequest,
    ToolExecutionResult,
)


class ToolLogRecord(Protocol):
    organization_id: str
    tool_name: str
    tool_call_id: str
    success: bool
    duration_ms: float


@pytest.mark.anyio
async def test_operational_tool_logs_success(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    organization_id = uuid.uuid4()
    customer_id = uuid.uuid4()

    async def fake_execute_list_customer_orders(
        **kwargs: object,
    ) -> ToolExecutionResult:
        return ToolExecutionResult(
            tool_name=(OperationalToolName.LIST_CUSTOMER_ORDERS),
            success=True,
            content="[]",
        )

    monkeypatch.setattr(
        executor_module,
        "execute_list_customer_orders",
        fake_execute_list_customer_orders,
    )

    tool_call = ToolCallRequest(
        call_id="call-123",
        tool_name=(OperationalToolName.LIST_CUSTOMER_ORDERS),
        arguments={
            "limit": 10,
        },
    )

    session = cast(
        AsyncSession,
        AsyncMock(
            spec=AsyncSession,
        ),
    )

    with caplog.at_level(logging.INFO):
        result = await execute_operational_tool_call(
            session=session,
            organization_id=organization_id,
            customer_id=customer_id,
            tool_call=tool_call,
        )

    assert result.success is True

    finished_record = cast(
        ToolLogRecord,
        next(record for record in caplog.records if record.message == "operational_tool_finished"),
    )

    assert finished_record.organization_id == str(organization_id)
    assert finished_record.tool_name == "list_customer_orders"
    assert finished_record.tool_call_id == "call-123"
    assert finished_record.success is True
    assert finished_record.duration_ms >= 0
