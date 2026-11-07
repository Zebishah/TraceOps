# IncidentIQ Architecture

IncidentIQ is a multi-tenant AI platform for investigating and resolving
operational incidents using company knowledge, AI reasoning, tools,
human approval, and auditable workflows.

## Current Architecture

The backend is built with FastAPI, PostgreSQL, Qdrant, S3-compatible
storage, LangChain, and external AI providers.

### Application Data

PostgreSQL is the source of truth for application data such as:

- organizations
- users
- memberships
- documents
- incidents

All organization-owned operations are tenant scoped.

### Document Ingestion

Documents follow this flow:

Upload
→ S3-compatible object storage
→ text extraction
→ page-aware chunking
→ Mistral embeddings
→ Qdrant indexing

PostgreSQL stores document metadata and processing state.

Qdrant stores searchable vector representations of document chunks.

### Retrieval

Retrieval is implemented explicitly rather than hidden behind a
framework abstraction:

Question or incident
→ Mistral query embedding
→ tenant-filtered Qdrant vector search
→ candidate chunks
→ Voyage reranking
→ top evidence chunks

This keeps tenant filtering, candidate selection, scores, metadata,
and reranking behavior under application control.

### LLM Application Layer

LangChain is used for application-level LLM interactions.

The shared `ChatGroq` model provides access to the configured Qwen
model through Groq.

LangChain is used for:

- prompt composition
- structured outputs
- output parsing
- reusable LLM components

Incident classification uses strict structured output so model results
are validated before entering application logic.

Grounded answer generation uses retrieved evidence and source labels
to produce cited answers.

### Incident Investigation Foundation

An incident contains:

- organization
- creator
- title
- description
- status
- category
- priority

Current incident flow:

Incident created
→ AI classification
→ category and priority persisted
→ status becomes investigating
→ incident converted into retrieval query
→ tenant-scoped evidence retrieved from company documents

### Provider Responsibilities

The architecture intentionally separates LLM application logic from
retrieval infrastructure.

LangChain:
- LLM calls
- prompts
- structured model output
- output parsing

Mistral:
- embeddings

Qdrant:
- vector storage and similarity search

Voyage:
- reranking

PostgreSQL:
- transactional application data

S3-compatible storage:
- original documents and extracted artifacts

## Next Phase

LangGraph will provide stateful workflow orchestration.

The initial investigation graph will evolve around:

START
→ classify incident
→ retrieve evidence
→ analyze evidence
→ recommend action
→ END

Later phases will add tool calling, human approval, execution,
verification, multi-agent review, persistence, observability,
evaluation, and automation.