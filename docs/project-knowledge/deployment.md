# Deployment Architecture

IncidentIQ is designed around managed cloud services.

# Frontend

The frontend is deployed separately from the backend, such as on Vercel.

# Backend

FastAPI is deployed as the primary application backend.

The MCP HTTP endpoint is intended to run with the backend rather than requiring a separate MCP service during the portfolio stage.

# PostgreSQL

Managed PostgreSQL stores transactional application state.

PostgreSQL is the source of truth for core business records.

# Vector Database

Qdrant Cloud stores:

- organization document vectors
- incident memory vectors
- IncidentIQ project knowledge vectors

These use separate collections.

# Redis

Managed Redis is used for caching and other optimization use cases.

A Redis failure should not normally replace PostgreSQL as the authoritative application store.

# Background Workflows

Inngest provides durable background workflow execution and retries.

# External Automation

n8n handles external integration workflows.

A deployed backend cannot use a localhost n8n webhook URL.

Production deployment requires a network-accessible n8n instance or endpoint.

# MCP Deployment

During local development, MCP can be tested using MCP Inspector.

For production, compatible clients connect over HTTPS to the MCP endpoint mounted in the IncidentIQ backend.