from datetime import UTC, datetime, timedelta
from decimal import Decimal

from ops_pilot.schemas.duplicate_payments import DuplicatePaymentCandidate
from ops_pilot.workflows.incident.checkpointing import get_checkpoint_serializer


def test_duplicate_candidate_survives_checkpoint_round_trip() -> None:
    original_time = datetime(2026, 11, 2, 12, 0, tzinfo=UTC)

    candidate = DuplicatePaymentCandidate(
        order_id="ORD-TEST",
        original_transaction_id="TXN-A",
        duplicate_transaction_id="TXN-B",
        amount=Decimal("12000.00"),
        currency="PKR",
        provider="stripe",
        original_processed_at=original_time,
        duplicate_processed_at=original_time + timedelta(seconds=60),
        seconds_apart=60,
    )

    serializer = get_checkpoint_serializer()

    restored = serializer.loads_typed(serializer.dumps_typed({"duplicate_payment": candidate}))

    assert isinstance(restored, dict)

    restored_candidate = restored["duplicate_payment"]

    assert isinstance(restored_candidate, DuplicatePaymentCandidate)
    assert restored_candidate.model_dump() == candidate.model_dump()
