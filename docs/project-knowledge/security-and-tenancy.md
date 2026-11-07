# Multi-Tenancy

TraceOps is designed as a multi-tenant system.

Organization-owned data must always be scoped by organization identity.

# PostgreSQL Isolation

Queries for organization-owned records include organization-level conditions.

Examples include:

- incidents
- customers
- approvals
- documents
- operational records

A database object ID alone is not sufficient authorization.

# Membership

Authenticated users must have membership in the organization they are attempting to access.

Organization membership is checked before protected API operations proceed.

# Vector Isolation

Qdrant company-document searches include organization filtering.

Incident-memory searches also include organization filtering.

Project knowledge is stored separately because it represents TraceOps documentation rather than tenant-owned company data.

# Sensitive Actions

Sensitive operations require backend authorization.

AI output is never treated as authorization.

Refund approval and execution rely on role checks, validation, deterministic data, and idempotency controls.

# Secrets

Infrastructure secrets such as API keys, webhook secrets, database credentials, and JWT secrets are stored in environment configuration and must not be committed to source control.

# MCP Security Direction

Operational MCP tools must not trust an organization identifier merely because an AI client provides it.

Remote MCP authentication should establish the caller identity.

That identity should determine organization membership and allowed capabilities before private operational data is returned.