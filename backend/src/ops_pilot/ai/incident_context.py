from collections import Counter

from pydantic import TypeAdapter, ValidationError

from ops_pilot.schemas.duplicate_payments import (
    DuplicatePaymentCandidate,
)
from ops_pilot.schemas.incident_memories import (
    IncidentMemoryRetrievalResult,
)
from ops_pilot.schemas.retrieval import RetrievalResult
from ops_pilot.tools.schemas import (
    OperationalToolName,
    PaymentTransactionData,
    ToolExecutionResult,
)


def format_incident_evidence(
    evidence: list[RetrievalResult],
) -> str:
    if not evidence:
        return "No supporting document evidence was retrieved."

    parts: list[str] = []

    for index, result in enumerate(evidence, start=1):
        parts.append(
            f"[SOURCE {index}]\n"
            f"File: {result.source_filename}\n"
            f"Page: {result.page_number}\n"
            f"Text:\n{result.text}"
        )

    return "\n\n".join(parts)


def format_payment_status_counts(
    result: ToolExecutionResult,
) -> str:
    """Describe current returned ledger rows without inferring past states."""
    if not result.success or result.tool_name != OperationalToolName.LIST_ORDER_PAYMENTS:
        return ""

    try:
        transactions = TypeAdapter(list[PaymentTransactionData]).validate_json(result.content)
    except ValidationError:
        return (
            "\nValidated payment status counts are unavailable. "
            "Do not infer transaction counts or historical statuses."
        )

    if not transactions:
        return "\nCurrent ledger status counts: no payment rows returned."

    counts = Counter(
        (
            transaction.transaction_type.value,
            transaction.status.value,
        )
        for transaction in transactions
    )

    lines = [
        "\nCurrent ledger status counts (returned rows only):",
    ]

    for (transaction_type, status), count in sorted(counts.items()):
        lines.append(f"- transaction_type={transaction_type}; status={status}; count={count}")

    lines.extend(
        [
            "A refunded charge is not currently a succeeded charge.",
            "These rows do not independently prove external money movement.",
            "Do not infer a charge's previous status from its current status.",
        ]
    )

    return "\n".join(lines)


def format_tool_results(
    results: list[ToolExecutionResult],
) -> str:
    if not results:
        return "No operational tool results were collected."

    parts: list[str] = []

    for index, result in enumerate(results, start=1):
        parts.append(
            f"[TOOL {index}]\n"
            f"Tool: {result.tool_name.value}\n"
            f"Success: {result.success}\n"
            f"Result:\n{result.content}"
            f"{format_payment_status_counts(result)}"
        )

    return "\n\n".join(parts)


def format_incident_memories(
    memories: list[IncidentMemoryRetrievalResult],
) -> str:
    if not memories:
        return "No similar historical incidents were retrieved."

    parts: list[str] = []

    for index, memory in enumerate(
        memories,
        start=1,
    ):
        parts.append(
            f"[MEMORY {index}]\n"
            f"Category: {memory.category}\n"
            f"Summary: {memory.summary}\n"
            f"Resolution: {memory.resolution}\n"
            f"Similarity score: {memory.vector_score:.4f}"
        )

    return "\n\n".join(parts)


def format_duplicate_payment_candidate(
    candidate: DuplicatePaymentCandidate | None,
) -> str:
    if candidate is None:
        return (
            "No verified duplicate-payment candidate was supplied to this AI step. "
            "This does not prove that duplicate charges never occurred, "
            "that every payment was inspected, or that the detector ran."
        )

    return (
        "A duplicate payment candidate was "
        "deterministically identified by TraceOps.\n"
        f"Order ID: {candidate.order_id}\n"
        f"Original transaction: "
        f"{candidate.original_transaction_id}\n"
        f"Duplicate transaction: "
        f"{candidate.duplicate_transaction_id}\n"
        f"Amount: {candidate.amount}\n"
        f"Currency: {candidate.currency}\n"
        f"Provider: {candidate.provider}\n"
        f"Seconds apart: {candidate.seconds_apart}"
    )
