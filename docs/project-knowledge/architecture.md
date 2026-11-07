# IncidentIQ Overview

IncidentIQ is a multi-tenant agentic incident investigation and resolution platform.

It combines company knowledge, live operational data, AI reasoning, deterministic safety rules, human approval, background processing, incident memory, and external business automation.

The system is designed so AI can investigate and recommend actions while sensitive operations remain controlled by deterministic backend logic and human approval.

# Main Components

The frontend communicates with a FastAPI backend.

PostgreSQL is the transactional source of truth.

Qdrant stores vector representations for company documents, incident memory, and project knowledge.

Redis is used as an optimization and caching layer.

S3-compatible object storage stores uploaded documents and extracted artifacts.

Mistral generates embeddings.

Voyage reranks retrieved passages.

Groq provides the configured Qwen model for language-model reasoning.

LangGraph orchestrates the internal AI incident workflow.

Inngest handles durable background processing.

n8n handles external business automation and third-party integrations.

MCP exposes selected IncidentIQ capabilities to compatible AI clients.

# Separation of Responsibilities

LangGraph controls AI reasoning and stateful incident investigation.

Inngest controls durable background jobs and retryable work.

n8n handles external business integrations such as Gmail, Discord, and Google Sheets.

MCP allows external AI clients to discover and invoke approved IncidentIQ capabilities.

PostgreSQL remains the source of truth for transactional application state.

Qdrant is used for semantic retrieval and memory search.

# Safety Philosophy

The language model is not trusted to perform sensitive financial actions directly.

AI is used for classification, analysis, explanation, and recommendation.

Deterministic backend logic verifies operational facts and constructs sensitive actions.

Human approval is required where policy requires it.

Execution is idempotent and verified before an incident is considered resolved.