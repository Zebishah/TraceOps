# n8n Purpose

IncidentIQ uses n8n for external business automation and integrations.

n8n is intentionally separate from LangGraph.

LangGraph controls AI reasoning and incident workflow state.

n8n connects completed business events to systems such as Gmail, Discord, and Google Sheets.

# High Risk Incident Automation

High or critical incidents can trigger a high-risk automation.

The automation can:

- notify the incident team through Discord
- send an alert email

The AI investigation continues after the notification.

# Incident Resolved Automation

When an incident is resolved, IncidentIQ can dispatch a resolved event.

The workflow can:

- notify the team
- email the customer when an email address exists

# Document Indexing Failure Automation

After durable indexing retries are exhausted, IncidentIQ can emit a document indexing failure event.

n8n can:

- notify operations through Discord
- send an operations email
- log the failed document and job to Google Sheets

# Customer Recovery Orchestrator

The Customer Recovery Orchestrator handles richer post-resolution business automation.

It can:

- route payment recovery events
- check whether a customer email exists
- send a customer resolution email
- log recovery information in Google Sheets
- check whether a refund exceeds a manager-review threshold
- create a manager follow-up
- notify a manager through Discord
- write normal or escalated audit records

# Webhook Security

IncidentIQ signs access to its n8n webhook workflows with a shared secret header.

The backend sends:

X-OpsPilot-Webhook-Secret

n8n validates the configured credential before accepting the webhook.

The secret is stored outside source control.

# Failure Isolation

n8n is an integration layer, not the transactional source of truth.

A temporary external automation failure should not undo a successfully verified core business operation.