import asyncio
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import cast
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from ops_pilot.core.exceptions import (
    ApprovalExecutionError,
)
from ops_pilot.models.approval import (
    ApprovalActionType,
    ApprovalRequest,
    ApprovalStatus,
)
from ops_pilot.models.incident import Incident, IncidentStatus
from ops_pilot.models.payment_transaction import (
    PaymentTransaction,
    PaymentTransactionStatus,
    PaymentTransactionType,
)
from ops_pilot.services.refund_execution import (
    execute_approved_refund,
)


class FakeScalarResult:
    def __init__(
        self,
        value: object | None,
    ) -> None:
        self.value = value

    def scalar_one_or_none(
        self,
    ) -> object | None:
        return self.value


class FakeSession:
    def __init__(
        self,
        results: list[object | None],
    ) -> None:
        self.results = list(results)
        self.added: list[object] = []
        self.commit_count = 0
        self.rollback_count = 0

    async def execute(
        self,
        statement,
    ) -> FakeScalarResult:
        if not self.results:
            raise AssertionError("Unexpected session.execute() call")

        return FakeScalarResult(self.results.pop(0))

    def add(
        self,
        value: object,
    ) -> None:
        self.added.append(value)

    async def commit(
        self,
    ) -> None:
        self.commit_count += 1

    async def rollback(
        self,
    ) -> None:
        self.rollback_count += 1

    async def refresh(
        self,
        value: object,
    ) -> None:
        return None


@pytest.mark.parametrize(
    "source_status, existing_results",
    [
        (PaymentTransactionStatus.REFUNDED, 1),
        (PaymentTransactionStatus.SUCCEEDED, 2),
    ],
)
def test_refund_recovery_rolls_back_on_commit_failure(
    source_status: PaymentTransactionStatus,
    existing_results: int,
) -> None:
    organization_id = uuid.uuid4()
    incident_id = uuid.uuid4()
    customer_id = uuid.uuid4()

    approval = make_approval(
        organization_id=organization_id,
        incident_id=incident_id,
    )

    source = make_source_transaction(
        organization_id=organization_id,
        status=source_status,
    )

    existing_refund = PaymentTransaction(
        id=uuid.uuid4(),
        organization_id=organization_id,
        order_id=source.order_id,
        source_transaction_id=source.id,
        external_transaction_id=f"refund-{approval.id}",
        provider=source.provider,
        transaction_type=PaymentTransactionType.REFUND,
        amount=source.amount,
        currency=source.currency,
        status=PaymentTransactionStatus.SUCCEEDED,
        processed_at=datetime.now(UTC),
    )

    results: list[object | None] = [
        make_incident(
            organization_id=organization_id,
            incident_id=incident_id,
        ),
        approval,
        source,
    ]

    if existing_results == 2:
        results.append(existing_refund)
    else:
        results.append(existing_refund)

    fake_session = FakeSession(results)
    session = cast(AsyncSession, fake_session)

    fake_session.commit = AsyncMock(
        side_effect=RuntimeError("Database commit failed"),
    )
    fake_session.rollback = AsyncMock()

    with pytest.raises(RuntimeError, match="Database commit failed"):
        asyncio.run(
            execute_approved_refund(
                session=session,
                organization_id=organization_id,
                incident_id=incident_id,
                approval_request_id=approval.id,
                customer_id=customer_id,
            )
        )

    fake_session.commit.assert_awaited_once()
    fake_session.rollback.assert_awaited_once()

    assert fake_session.added == []


def make_approval(
    *,
    organization_id: uuid.UUID,
    incident_id: uuid.UUID,
    amount: str = "12000.00",
    currency: str = "PKR",
    status: ApprovalStatus = ApprovalStatus.APPROVED,
) -> ApprovalRequest:
    approval = ApprovalRequest(
        id=uuid.uuid4(),
        organization_id=organization_id,
        incident_id=incident_id,
        workflow_thread_id="test-thread",
        action_type=(ApprovalActionType.REFUND_TRANSACTION),
        action_payload={
            "external_transaction_id": "TXN-123",
            "amount": amount,
            "currency": currency,
        },
        reason="Confirmed duplicate payment.",
        status=status,
    )

    if status in {
        ApprovalStatus.APPROVED,
        ApprovalStatus.EXECUTED,
    }:
        approval.decided_by_user_id = uuid.uuid4()
        approval.decided_at = datetime.now(UTC)

    return approval


def make_source_transaction(
    *,
    organization_id: uuid.UUID,
    amount: Decimal = Decimal("12000.00"),
    currency: str = "PKR",
    status: PaymentTransactionStatus = (PaymentTransactionStatus.SUCCEEDED),
) -> PaymentTransaction:
    return PaymentTransaction(
        id=uuid.uuid4(),
        organization_id=organization_id,
        order_id=uuid.uuid4(),
        source_transaction_id=None,
        external_transaction_id="TXN-123",
        provider="stripe",
        transaction_type=(PaymentTransactionType.CHARGE),
        amount=amount,
        currency=currency,
        status=status,
        processed_at=datetime.now(UTC),
    )


def test_execute_approved_refund_creates_refund() -> None:
    organization_id = uuid.uuid4()
    incident_id = uuid.uuid4()
    customer_id = uuid.uuid4()

    approval = make_approval(
        organization_id=organization_id,
        incident_id=incident_id,
    )

    source = make_source_transaction(
        organization_id=organization_id,
    )

    fake_session = FakeSession(
        [
            make_incident(
                organization_id=organization_id,
                incident_id=incident_id,
            ),
            approval,
            source,
            None,
        ]
    )

    session = cast(
        AsyncSession,
        fake_session,
    )

    result = asyncio.run(
        execute_approved_refund(
            session=session,
            organization_id=organization_id,
            incident_id=incident_id,
            approval_request_id=approval.id,
            customer_id=customer_id,
        )
    )

    assert result.source_transaction_id == "TXN-123"

    assert result.refund_transaction_id == (f"refund-{approval.id}")

    assert result.amount == Decimal("12000.00")
    assert result.currency == "PKR"
    assert result.already_executed is False

    assert source.status == (PaymentTransactionStatus.REFUNDED)

    assert approval.status == (ApprovalStatus.EXECUTED)

    assert approval.executed_at is not None

    assert len(fake_session.added) == 1

    refund = fake_session.added[0]

    assert isinstance(
        refund,
        PaymentTransaction,
    )

    assert refund.transaction_type == (PaymentTransactionType.REFUND)

    assert refund.source_transaction_id == (source.id)

    assert refund.amount == source.amount
    assert refund.currency == source.currency

    assert fake_session.commit_count == 1


def test_execute_refund_blocks_amount_mismatch() -> None:
    organization_id = uuid.uuid4()
    incident_id = uuid.uuid4()
    customer_id = uuid.uuid4()

    approval = make_approval(
        organization_id=organization_id,
        incident_id=incident_id,
        amount="9000.00",
    )

    source = make_source_transaction(
        organization_id=organization_id,
        amount=Decimal("12000.00"),
    )

    fake_session = FakeSession(
        [
            make_incident(
                organization_id=organization_id,
                incident_id=incident_id,
            ),
            approval,
            source,
        ]
    )

    session = cast(
        AsyncSession,
        fake_session,
    )

    with pytest.raises(
        ApprovalExecutionError,
        match="amount",
    ):
        asyncio.run(
            execute_approved_refund(
                session=session,
                organization_id=organization_id,
                incident_id=incident_id,
                approval_request_id=approval.id,
                customer_id=customer_id,
            )
        )

    assert fake_session.added == []

    assert source.status == (PaymentTransactionStatus.SUCCEEDED)


def test_execute_refund_blocks_currency_mismatch() -> None:
    organization_id = uuid.uuid4()
    incident_id = uuid.uuid4()
    customer_id = uuid.uuid4()

    approval = make_approval(
        organization_id=organization_id,
        incident_id=incident_id,
        currency="USD",
    )

    source = make_source_transaction(
        organization_id=organization_id,
        currency="PKR",
    )

    fake_session = FakeSession(
        [
            make_incident(
                organization_id=organization_id,
                incident_id=incident_id,
            ),
            approval,
            source,
        ]
    )

    session = cast(
        AsyncSession,
        fake_session,
    )

    with pytest.raises(
        ApprovalExecutionError,
        match="currency",
    ):
        asyncio.run(
            execute_approved_refund(
                session=session,
                organization_id=organization_id,
                incident_id=incident_id,
                approval_request_id=approval.id,
                customer_id=customer_id,
            )
        )

    assert fake_session.added == []


def test_execute_refund_requires_approved_request() -> None:
    organization_id = uuid.uuid4()
    incident_id = uuid.uuid4()
    customer_id = uuid.uuid4()

    approval = make_approval(
        organization_id=organization_id,
        incident_id=incident_id,
        status=ApprovalStatus.PENDING,
    )

    fake_session = FakeSession(
        [
            make_incident(
                organization_id=organization_id,
                incident_id=incident_id,
            ),
            approval,
        ]
    )

    session = cast(
        AsyncSession,
        fake_session,
    )

    with pytest.raises(
        ApprovalExecutionError,
        match="approved",
    ):
        asyncio.run(
            execute_approved_refund(
                session=session,
                organization_id=organization_id,
                incident_id=incident_id,
                approval_request_id=approval.id,
                customer_id=customer_id,
            )
        )

    assert fake_session.added == []


def test_execute_refund_retry_returns_existing_refund() -> None:
    organization_id = uuid.uuid4()
    incident_id = uuid.uuid4()
    customer_id = uuid.uuid4()

    approval = make_approval(
        organization_id=organization_id,
        incident_id=incident_id,
        status=ApprovalStatus.EXECUTED,
    )

    approval.executed_at = datetime.now(UTC)

    existing_refund = PaymentTransaction(
        id=uuid.uuid4(),
        organization_id=organization_id,
        order_id=uuid.uuid4(),
        source_transaction_id=uuid.uuid4(),
        external_transaction_id=(f"refund-{approval.id}"),
        provider="stripe",
        transaction_type=(PaymentTransactionType.REFUND),
        amount=Decimal("12000.00"),
        currency="PKR",
        status=(PaymentTransactionStatus.SUCCEEDED),
        processed_at=datetime.now(UTC),
    )

    fake_session = FakeSession(
        [
            make_incident(
                organization_id=organization_id,
                incident_id=incident_id,
            ),
            approval,
            existing_refund,
        ]
    )

    session = cast(
        AsyncSession,
        fake_session,
    )

    result = asyncio.run(
        execute_approved_refund(
            session=session,
            organization_id=organization_id,
            incident_id=incident_id,
            approval_request_id=approval.id,
            customer_id=customer_id,
        )
    )

    assert result.already_executed is True

    assert result.refund_transaction_id == (existing_refund.external_transaction_id)

    assert fake_session.added == []
    assert fake_session.commit_count == 0


def test_execute_refund_blocks_transaction_from_other_customer() -> None:
    organization_id = uuid.uuid4()
    incident_id = uuid.uuid4()
    customer_id = uuid.uuid4()

    approval = make_approval(
        organization_id=organization_id,
        incident_id=incident_id,
    )

    fake_session = FakeSession(
        [
            make_incident(
                organization_id=organization_id,
                incident_id=incident_id,
            ),
            approval,
            None,
        ]
    )

    session = cast(
        AsyncSession,
        fake_session,
    )

    with pytest.raises(
        ApprovalExecutionError,
        match="Source transaction not found",
    ):
        asyncio.run(
            execute_approved_refund(
                session=session,
                organization_id=organization_id,
                incident_id=incident_id,
                approval_request_id=approval.id,
                customer_id=customer_id,
            )
        )

    assert fake_session.added == []


def test_execute_refund_rejects_approval_without_human_identity() -> None:
    organization_id = uuid.uuid4()
    incident_id = uuid.uuid4()
    customer_id = uuid.uuid4()

    approval = make_approval(
        organization_id=organization_id,
        incident_id=incident_id,
    )

    approval.decided_by_user_id = None
    approval.decided_at = None

    fake_session = FakeSession(
        [
            make_incident(
                organization_id=organization_id,
                incident_id=incident_id,
            ),
            approval,
        ]
    )

    session = cast(
        AsyncSession,
        fake_session,
    )

    with pytest.raises(
        ApprovalExecutionError,
        match="recorded human approval",
    ):
        asyncio.run(
            execute_approved_refund(
                session=session,
                organization_id=organization_id,
                incident_id=incident_id,
                approval_request_id=approval.id,
                customer_id=customer_id,
            )
        )

    assert fake_session.added == []
    assert fake_session.commit_count == 0


def make_incident(
    *,
    organization_id: uuid.UUID,
    incident_id: uuid.UUID,
    status: IncidentStatus = IncidentStatus.AWAITING_APPROVAL,
) -> Incident:
    return Incident(
        id=incident_id,
        organization_id=organization_id,
        title="Duplicate payment investigation",
        description="Customer reported a duplicate charge.",
        status=status,
    )
