# Incident closure without an operational action

An authorized owner, administrator, or reviewer opens **Resolve incident** after reviewing the investigation. The form records an outcome, findings and justification, customer-facing message, and next steps. The message preview can be copied for review or communication.

The full record is saved in the existing `incidents.resolution_reason` text field. The existing resolver ID and resolution timestamp identify the person and time. This needs no database migration. Existing reason-only API clients remain compatible with `POST /api/v1/organizations/{organization_id}/incidents/{incident_id}/resolve-no-action`.

Detailed requests add `outcome`, `customer_message`, and `next_steps` to `reason`. All three added fields are required together; whitespace-only values and unsupported outcomes are rejected. Outcomes are `no_issue_found`, `already_corrected`, `guidance_provided`, and `resolved_externally`.

The UI hides manual closure while a known background investigation is active, additional information is requested, or a pending, approved, or executed proposal exists. The backend retains its row lock, reviewer authorization, investigating-only rule, and approval conflict checks. AI completion alone does not close an incident, and this flow cannot execute a refund.

Closure and the existing `incident.resolved` outbox event are committed together. The event now includes `resolution_reason` for downstream follow-through. The customer message is a **recorded draft**: the application does not claim it was sent or delivered. Existing n8n templates require separate configuration to use the added context. Delivery can be inspected under Automations; webhook acceptance itself is not customer delivery.

After saving, the incident displays its durable resolution record above the investigation. A legacy or refund resolution displays its existing reason without inventing missing outcome details.

## Verification

Backend checks cover legacy compatibility, complete detailed requests, whitespace validation, unsupported outcomes, durable record construction, and outbox rollback. Existing tests retain status and blocking-approval coverage. Frontend contract checks cover every outcome, incomplete explanations, and request limits.
