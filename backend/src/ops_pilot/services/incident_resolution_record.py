"""Build a durable, readable closure record without changing legacy API clients."""

OUTCOME_LABELS = {
    "no_issue_found": "No issue found",
    "already_corrected": "Already corrected",
    "guidance_provided": "Guidance provided",
    "resolved_externally": "Resolved outside OpsPilot",
}


def format_resolution_record(
    *,
    reason: str,
    outcome: str | None = None,
    customer_message: str | None = None,
    next_steps: str | None = None,
) -> str:
    """Persist the outcome and message together in the existing resolution field.

    Customer wording is a recorded draft, not evidence of notification delivery.
    Existing callers that supply only a reason keep their original record format.
    """
    reason = reason.strip()
    if not 10 <= len(reason) <= 1000:
        raise ValueError("Resolution summary must contain 10 to 1000 characters")
    if outcome is not None and outcome not in OUTCOME_LABELS:
        raise ValueError("Unsupported resolution outcome")
    customer_message = customer_message.strip() if customer_message is not None else None
    next_steps = next_steps.strip() if next_steps is not None else None
    if customer_message is not None and not 10 <= len(customer_message) <= 1000:
        raise ValueError("Customer message must contain 10 to 1000 characters")
    if next_steps is not None and not 10 <= len(next_steps) <= 500:
        raise ValueError("Next steps must contain 10 to 500 characters")
    if outcome is None:
        if customer_message is not None or next_steps is not None:
            raise ValueError("A resolution outcome is required for a detailed closure")
        return reason
    if customer_message is None or next_steps is None:
        raise ValueError("Detailed closure requires customer wording and next steps")
    return "\n\n".join(
        [
            f"Outcome: {OUTCOME_LABELS[outcome]}",
            f"Investigation and resolution summary:\n{reason}",
            f"Customer message (recorded draft):\n{customer_message}",
            f"Follow-up and next steps:\n{next_steps}",
            "Communication status: Message recorded; customer delivery is not confirmed.",
        ]
    )
