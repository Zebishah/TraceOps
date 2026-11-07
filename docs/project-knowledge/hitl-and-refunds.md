# Human in the Loop

TraceOps uses human-in-the-loop approval for sensitive actions such as financial refunds.

The AI is allowed to investigate and recommend an action, but sensitive execution can require explicit approval.

# Approval Flow

The workflow follows this general pattern:

investigation
→ recommendation
→ deterministic action proposal
→ approval required
→ workflow pauses
→ reviewer approves or rejects
→ workflow resumes

# Approval Roles

Approval decisions are restricted to authorized organization members such as reviewers, administrators, or owners.

Authorization is checked by the backend rather than trusted to the AI client.

# Refund Execution

Refund execution validates the approved action against the underlying payment transaction.

The backend validates information such as:

- organization ownership
- approval state
- source transaction
- amount
- currency
- previous execution state

# Idempotency

Refund execution is designed to be idempotent.

If an approved action was already executed, repeating the execution path should not create a second refund.

Existing refund records are checked before creating a new one.

# Verification

Execution alone is not enough.

The workflow verifies that the expected operational state has been reached before treating the incident as resolved.

# Why This Design Exists

The system deliberately separates:

AI recommendation
→ human authorization
→ deterministic execution

This prevents a language model from directly controlling irreversible financial operations.