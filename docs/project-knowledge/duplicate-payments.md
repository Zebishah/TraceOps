# Duplicate Payment Detection

IncidentIQ includes deterministic duplicate-payment detection for payment incidents.

This logic was introduced because a language model should not guess which financial transaction should be refunded.

# Detection Rule

The detector considers successful charge transactions.

A duplicate candidate requires two eligible charges with matching:

- amount
- currency
- provider

The transactions must also occur within the configured duplicate-payment time window.

The later matching charge is treated as the duplicate candidate.

# Ambiguity Safety

IncidentIQ does not force a conclusion when multiple possible duplicate candidates exist.

If the available transaction history is ambiguous, the detector returns no deterministic candidate.

The system prefers refusing to guess over performing the wrong financial action.

# Division of Responsibility

AI can explain why the payment history appears suspicious.

Deterministic backend logic identifies the exact candidate transaction.

This means:

AI:
understanding and explanation

Backend:
exact financial selection and safety

Human:
approval when required

# Refund Selection

When a verified duplicate candidate exists, the exact source transaction, amount, and currency used by the proposed refund come from verified operational data rather than free-form model output.