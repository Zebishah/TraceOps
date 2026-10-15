# MCP Purpose

OpsPilot implements a Model Context Protocol server so compatible AI clients can discover and invoke approved OpsPilot capabilities.

MCP does not replace the FastAPI API or LangGraph.

It provides an AI-oriented integration layer.

# Project Knowledge MCP

The first MCP capability is project knowledge search.

An external AI can ask questions about OpsPilot such as:

- how the architecture works
- why LangGraph is used
- how n8n fits into the system
- how duplicate-payment detection works
- how human approval works
- how retrieval works

The MCP tool searches a dedicated Qdrant project-knowledge collection.

# Why the MCP Tool Returns Evidence

The external MCP client is already an AI model.

OpsPilot therefore returns structured project evidence rather than always using another LLM to produce a second final answer.

The flow is:

AI client
→ MCP tool
→ project knowledge retrieval
→ relevant evidence
→ AI client produces the final response

# Operational MCP

OpsPilot will also expose carefully selected operational read-only tools.

Planned examples include:

- list open incidents
- search incidents
- get an incident
- retrieve relevant incident memory
- inspect customer or payment information where authorized

# Reuse Existing Services

MCP tools should remain thin.

They should call the same application service layer used by FastAPI and internal workflows rather than reimplementing SQL or business logic inside MCP handlers.

# Safety

Read-only capabilities are exposed first.

Sensitive actions must not bypass existing authorization, approval, idempotency, or verification controls.

# Remote Deployment

The production MCP server will use HTTP transport and be exposed through the deployed OpsPilot backend.

The intended architecture is:

MCP client
→ HTTPS
→ OpsPilot backend
→ MCP server
→ existing OpsPilot services