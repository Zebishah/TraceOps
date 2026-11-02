import json

import pytest
from langchain_core.messages import AIMessage

from ops_pilot.ai.incident_context import (
    format_duplicate_payment_candidate,
    format_payment_status_counts,
)
from ops_pilot.ai.output_validation import (
    InvalidAIOutputError,
    validate_text_response,
)
from ops_pilot.tools.schemas import (
    OperationalToolName,
    ToolExecutionResult,
)


def test_refunded_charge_is_not_counted_as_succeeded() -> None:
    common = {
        "provider": "stripe",
        "amount": "12000.00",
        "currency": "PKR",
        "processed_at": None,
        "payment_instrument_fingerprint": None,
    }

    rows = [
        {
            **common,
            "external_transaction_id": "charge-original",
            "transaction_type": "charge",
            "status": "succeeded",
        },
        {
            **common,
            "external_transaction_id": "charge-refunded",
            "transaction_type": "charge",
            "status": "refunded",
        },
        {
            **common,
            "external_transaction_id": "refund-record",
            "transaction_type": "refund",
            "status": "succeeded",
        },
    ]

    summary = format_payment_status_counts(
        ToolExecutionResult(
            tool_name=OperationalToolName.LIST_ORDER_PAYMENTS,
            success=True,
            content=json.dumps(rows),
        )
    )

    assert "transaction_type=charge; status=succeeded; count=1" in summary
    assert "transaction_type=charge; status=refunded; count=1" in summary
    assert "transaction_type=refund; status=succeeded; count=1" in summary
    assert "transaction_type=charge; status=succeeded; count=2" not in summary


def test_failed_payment_tool_has_no_status_summary() -> None:
    summary = format_payment_status_counts(
        ToolExecutionResult(
            tool_name=OperationalToolName.LIST_ORDER_PAYMENTS,
            success=False,
            content="Unavailable",
        )
    )

    assert summary == ""


def test_missing_candidate_does_not_claim_exhaustive_detection() -> None:
    text = format_duplicate_payment_candidate(None)

    assert "No verified duplicate-payment candidate was supplied" in text
    assert "does not prove" in text


def test_candidate_input_has_its_own_validated_citation() -> None:
    message = AIMessage(
        content="No verified candidate was supplied [DETECTION 1].",
    )

    assert (
        validate_text_response(
            message,
            source_count=0,
            tool_successes=[],
            memory_count=0,
            detection_count=1,
            empty_error="Empty",
        )
        == message.content
    )

    with pytest.raises(InvalidAIOutputError):
        validate_text_response(
            message,
            source_count=0,
            tool_successes=[],
            memory_count=0,
            detection_count=0,
            empty_error="Empty",
        )
