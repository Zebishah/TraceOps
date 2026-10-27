import asyncio
import json
import uuid
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest

from ops_pilot.models.approval import (
    ApprovalActionType,
    ApprovalRequest,
    ApprovalStatus,
)
from ops_pilot.models.incident import (
    IncidentPriority,
    IncidentStatus,
)
from ops_pilot.schemas.incident_actions import IncidentActionProposal
from ops_pilot.schemas.incident_classification import (
    IncidentCategory,
)
from ops_pilot.services.approvals import create_or_get_pending_approval
from ops_pilot.services.duplicate_payment_detection import (
    detect_duplicate_payment_candidate,
)
from ops_pilot.services.incident_resolution import (
    IncidentResolutionConflict,
)
from ops_pilot.tools.schemas import (
    OperationalToolName,
    ToolExecutionResult,
)
from ops_pilot.workflows.incident.nodes import propose_action_node


def with_verified_order_evidence(
    tool_results: list[ToolExecutionResult],
) -> list[ToolExecutionResult]:
    """Add a paid synthetic order matching the payment fixture."""
    payment_result = next(
        result
        for result in tool_results
        if result.tool_name == OperationalToolName.LIST_ORDER_PAYMENTS
    )

    order_id = payment_result.arguments["order_id"]
    payments = json.loads(payment_result.content)

    if (
        not isinstance(order_id, str)
        or not isinstance(payments, list)
        or not payments
        or not isinstance(payments[0], dict)
    ):
        raise AssertionError("Invalid test payment fixture")

    first_payment = payments[0]

    order_result = ToolExecutionResult(
        call_id="verified-test-order",
        tool_name=OperationalToolName.LIST_CUSTOMER_ORDERS,
        arguments={"limit": 10},
        success=True,
        content=json.dumps(
            [
                {
                    "external_order_id": order_id,
                    "product_name": "Synthetic test product",
                    "total_amount": first_payment["amount"],
                    "currency": first_payment["currency"],
                    "status": "paid",
                    "ordered_at": "2026-10-08T09:00:00Z",
                }
            ]
        ),
    )

    return [order_result, *tool_results]


def make_workflow_state(
    category: IncidentCategory,
) -> dict[str, object]:
    return {
        "title": "Payment investigation",
        "description": "A customer reported duplicate billing.",
        "category": category,
        "priority": IncidentPriority.HIGH,
        "evidence": [],
        "analysis": "Insufficient verified payment evidence.",
        "recommended_action": "Request human investigation.",
        "tool_results": [],
        "duplicate_payment_candidate": None,
    }


@pytest.mark.parametrize(
    "category",
    [
        IncidentCategory.ACCESS,
        IncidentCategory.SYSTEM,
    ],
)
def test_nonpayment_cannot_create_refund(
    category: IncidentCategory,
) -> None:
    state = make_workflow_state(category)

    with patch(
        "ops_pilot.workflows.incident.nodes.has_required_operational_evidence",
        return_value=True,
    ):
        result = asyncio.run(
            propose_action_node(state)  # type: ignore[arg-type]
        )

    assert result["proposed_action"] is None
    assert result["approval_required"] is False


@pytest.mark.parametrize(
    ("first_provider", "second_provider", "expected"),
    [
        ("stripe", "stripe", True),
        ("paypal", "paypal", True),
        ("stripe", "paypal", False),
        ("paypal", "stripe", False),
        ("", "stripe", False),
        ("unknown", "unknown", False),
        ("stripe", "unknown", False),
    ],
)
def test_duplicate_detection_requires_supported_matching_provider(
    first_provider: str,
    second_provider: str,
    expected: bool,
) -> None:
    payments = [
        {
            "external_transaction_id": "charge-1",
            "provider": first_provider,
            "payment_instrument_fingerprint": "fingerprint-1",
            "transaction_type": "charge",
            "amount": "100.00",
            "currency": "USD",
            "status": "succeeded",
            "processed_at": "2026-10-20T10:00:00Z",
        },
        {
            "external_transaction_id": "charge-2",
            "provider": second_provider,
            "payment_instrument_fingerprint": "fingerprint-1",
            "transaction_type": "charge",
            "amount": "100.00",
            "currency": "USD",
            "status": "succeeded",
            "processed_at": "2026-10-20T10:01:00Z",
        },
    ]

    tool_result = ToolExecutionResult(
        call_id="provider-test",
        tool_name=OperationalToolName.LIST_ORDER_PAYMENTS,
        arguments={"order_id": "order-1"},
        success=True,
        content=json.dumps(payments),
    )

    candidate = detect_duplicate_payment_candidate(
        tool_results=with_verified_order_evidence([tool_result]),
    )

    assert (candidate is not None) is expected


def make_proposal() -> IncidentActionProposal:
    return IncidentActionProposal(
        requires_approval=True,
        action_type=ApprovalActionType.REFUND_TRANSACTION,
        external_transaction_id="charge-2",
        amount=Decimal("100.00"),
        currency="USD",
        reason="Verified duplicate payment requires human approval.",
    )


@pytest.mark.asyncio
async def test_different_thread_cannot_create_second_pending_approval() -> None:
    organization_id = uuid.uuid4()
    incident_id = uuid.uuid4()

    incident = SimpleNamespace(
        id=incident_id,
        organization_id=organization_id,
        status=IncidentStatus.AWAITING_APPROVAL,
    )

    existing_approval = ApprovalRequest(
        id=uuid.uuid4(),
        organization_id=organization_id,
        incident_id=incident_id,
        workflow_thread_id="original-thread",
        action_type=ApprovalActionType.REFUND_TRANSACTION,
        action_payload={
            "external_transaction_id": "charge-2",
            "amount": "100.00",
            "currency": "USD",
        },
        reason="Verified duplicate payment.",
        status=ApprovalStatus.PENDING,
    )

    incident_result = Mock()
    incident_result.scalar_one_or_none.return_value = incident

    active_result = Mock()
    active_result.scalars.return_value.all.return_value = [existing_approval]

    session = AsyncMock()
    session.execute.side_effect = [incident_result, active_result]

    from ops_pilot.core.exceptions import ApprovalDecisionConflictError

    with pytest.raises(
        ApprovalDecisionConflictError,
        match="Another active approval already exists",
    ):
        await create_or_get_pending_approval(
            session=session,
            organization_id=organization_id,
            incident_id=incident_id,
            workflow_thread_id="different-thread",
            proposal=make_proposal(),
        )

    session.add.assert_not_called()
    session.commit.assert_not_awaited()
    session.rollback.assert_awaited_once()
    assert session.execute.await_count == 2


@pytest.mark.asyncio
async def test_same_thread_matching_approval_is_reused() -> None:
    organization_id = uuid.uuid4()
    incident_id = uuid.uuid4()

    incident = SimpleNamespace(
        id=incident_id,
        organization_id=organization_id,
        status=IncidentStatus.AWAITING_APPROVAL,
    )

    existing = ApprovalRequest(
        id=uuid.uuid4(),
        organization_id=organization_id,
        incident_id=incident_id,
        workflow_thread_id="same-thread",
        action_type=ApprovalActionType.REFUND_TRANSACTION,
        action_payload={
            "external_transaction_id": "charge-2",
            "amount": "100.00",
            "currency": "USD",
        },
        reason="Verified duplicate.",
        status=ApprovalStatus.PENDING,
    )

    incident_result = Mock()
    incident_result.scalar_one_or_none.return_value = incident

    active_result = Mock()
    active_result.scalars.return_value.all.return_value = [existing]

    session = AsyncMock()
    session.execute.side_effect = [incident_result, active_result]

    approval = await create_or_get_pending_approval(
        session=session,
        organization_id=organization_id,
        incident_id=incident_id,
        workflow_thread_id="same-thread",
        proposal=make_proposal(),
    )

    assert approval is existing
    session.add.assert_not_called()
    session.commit.assert_not_awaited()
    session.rollback.assert_awaited_once()
    assert session.execute.await_count == 2


@pytest.mark.asyncio
async def test_classification_during_pending_approval_is_rejected() -> None:
    from ops_pilot.services import incident_classification as service

    organization_id = uuid.uuid4()
    incident_id = uuid.uuid4()

    incident = SimpleNamespace(
        id=incident_id,
        title="Duplicate charge",
        description="Customer reports two charges.",
        status=IncidentStatus.AWAITING_APPROVAL,
    )

    session = AsyncMock()

    with patch.object(
        service,
        "get_incident",
        new=AsyncMock(return_value=incident),
    ):
        with pytest.raises(
            IncidentResolutionConflict,
            match="current state",
        ):
            await service.classify_stored_incident(
                session=session,
                organization_id=organization_id,
                incident_id=incident_id,
            )

    session.commit.assert_not_awaited()
