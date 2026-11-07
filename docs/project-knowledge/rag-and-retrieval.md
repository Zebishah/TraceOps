# Retrieval Overview

IncidentIQ uses retrieval-augmented generation to ground AI reasoning in company knowledge.

The retrieval pipeline is implemented explicitly so tenant filtering, metadata, candidate selection, reranking, and evidence scores remain under application control.

# Document Ingestion

Uploaded documents follow this flow:

Upload
→ S3-compatible storage
→ text extraction
→ page-aware chunking
→ Mistral embeddings
→ Qdrant indexing

PostgreSQL stores document metadata and processing state.

Qdrant stores searchable vector representations of document chunks.

# Retrieval Pipeline

A query follows this flow:

Question or incident
→ Mistral query embedding
→ Qdrant vector search
→ tenant filtering
→ candidate chunks
→ Voyage reranking
→ top evidence

Vector similarity is used for candidate discovery.

Voyage reranking is used to determine which candidate passages are most relevant to the exact query.

# Tenant Isolation

Company document retrieval always includes organization-level filtering.

A request from one organization must not retrieve vectors owned by another organization.

The organization identifier is stored in Qdrant payload metadata and applied as a search filter.

# Evidence

Retrieved evidence contains metadata including:

- document ID
- chunk ID
- chunk index
- page number
- source filename
- vector similarity score
- reranker score
- chunk text

This evidence is passed into grounded reasoning rather than asking the language model to invent company facts.

# Project Knowledge Retrieval

MCP project knowledge uses a separate Qdrant collection from customer or organization documents.

The project knowledge collection contains curated IncidentIQ architecture and implementation documentation.

This separation prevents public or portfolio-oriented project documentation from being mixed with organization-owned operational knowledge.