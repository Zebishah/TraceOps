# IncidentIQ

**AI-assisted incident investigation, with evidence before action.**

IncidentIQ investigates operational incidents using organization knowledge, live business records, AI agents, and human oversight. It brings the investigation, evidence, proposed next steps, approvals, and execution history into one multi-tenant workspace.

Previously branded OpsPilot, this repository now uses IncidentIQ as its product identity.

## What it does

- Classifies incidents and runs investigator/reviewer workflows with LangGraph.
- Retrieves company documents and historical incident memory with tenant-scoped retrieval, reranking, and citations.
- Inspects authorized customer, order, and payment records through bounded tools.
- Proposes next steps, requests missing information, and supports resolution with or without an approved action.
- Pauses sensitive workflows for explicit human approval and preserves resumable state.
- Runs background investigations, indexing, retries, and recovery with Inngest.
- Records automation delivery attempts and hands events to configured n8n workflows.
- Exposes scoped incident and knowledge tools to authorized MCP clients, including OAuth connection screens.
- Provides voice input and an optional incident-classifier fine-tuning workspace with evaluation tooling.
- Presents incident, knowledge, approval, automation, readiness, and evaluation screens in a React workspace.

## Technology

| Layer | Stack |
|---|---|
| Backend | Python 3.12+, FastAPI, Pydantic, SQLAlchemy, Alembic |
| Agents | LangGraph, LangChain, Groq |
| Retrieval | Qdrant, Mistral embeddings, Voyage reranking, document and incident-memory retrieval |
| Durable state | PostgreSQL, LangGraph PostgreSQL checkpoints |
| Infrastructure | Redis, AWS S3, Inngest, n8n |
| AI integrations | Model Context Protocol, OAuth, voice/STT endpoints, optional Qwen fine-tuning tooling |
| Frontend | React 19, TypeScript, Next.js App Router conventions, Vinext/Vite, Tailwind CSS, shadcn/Radix, Recharts |
| Quality | pytest, Ruff, mypy, frontend Node.js tests, TypeScript, ESLint |

## How an investigation works

1. An authenticated user creates an incident within an organization.
2. The workflow classifies it, retrieves relevant knowledge, and inspects permitted records.
3. Investigator and reviewer stages produce evidence-backed findings and a recommended next step.
4. Missing information can trigger a clarification request. Sensitive proposals wait for human approval.
5. The system records the result, action or resolution, saved state, and automation-delivery history.

PostgreSQL is the source of truth. Qdrant stores retrieval vectors; Redis supports caching. Inngest runs durable background work. n8n handles configured external automation. The frontend uses a server-side backend proxy, and backend authorization determines record access.

## Repository layout

| Path | Responsibility |
|---|---|
| `backend/src/ops_pilot/` | API, agents, retrieval, workflows, services, MCP, and integrations |
| `backend/migrations/` | Alembic database migrations |
| `backend/tests/` | Backend unit, contract, and integration coverage |
| `backend/finetuning/` | Optional model training, serving, and evaluation tools |
| `backend/infrastructure/n8n/` | Importable automation workflow definitions |
| `frontend/` | Landing page, authenticated workspace, and backend proxy |
| `docs/` | Architecture, authentication, knowledge, and deployment guides |

## Local development

Requirements: Python 3.12+, uv, Node.js 22, the frontend's pinned pnpm version, and a PostgreSQL database. Retrieval and integration features require the corresponding provider configuration in the backend example.

```bash
git clone https://github.com/Zebishah/ops-pilot.git
cd ops-pilot/backend
cp .env.example .env
uv sync
```

Configure `DATABASE_URL`, a strong `JWT_SECRET_KEY`, and the provider settings for the features you will run. Set `APP_NAME="IncidentIQ API"`. PostgreSQL, Qdrant, Redis, S3, embedding, reranking, Groq, Inngest, and n8n settings are documented in [the environment template](backend/.env.example). Never use example secrets in a shared deployment.

```bash
# From ops-pilot/backend/
uv run alembic upgrade head
uv run uvicorn ops_pilot.main:app --reload --host 127.0.0.1 --port 8000
```

In a second terminal, from the repository root:

```bash
cd frontend
cp .env.example .env.local
pnpm install --frozen-lockfile
pnpm dev
```

Set `OPSPILOT_BACKEND_URL=http://127.0.0.1:8000` in `frontend/.env.local`. This existing server-only setting remains the backend connection contract. Open the development URL printed by the frontend; API documentation is at `http://127.0.0.1:8000/docs`.

Background jobs require configured Inngest execution; importing n8n definitions alone does not run them. See [the frontend guide](frontend/README.md), [architecture](docs/architecture.md), and [authentication rollout](docs/authentication-readiness.md).

## Verification

```bash
# From ops-pilot/backend/
uv run ruff check .
uv run mypy
uv run pytest

# From ops-pilot/frontend/
pnpm run typecheck
pnpm test
pnpm run build
```

Integration tests and end-to-end workflows require their external dependencies and appropriate credentials. Optional fine-tuning has its own dependencies in `backend/finetuning/pyproject.toml`; it is separate from the API runtime.

## Demonstration boundaries

The public walkthrough uses synthetic records. The current refund demonstration records a simulated action in the internal ledger; it does not move money through a payment provider. n8n availability depends on the configured host; delivery acceptance and downstream completion are separate states. Training and voice features depend on the selected providers and deployed workers.

## Branding compatibility

IncidentIQ is the product name across the UI, API metadata, email, MCP connection screens, and documentation. The GitHub repository URL, Python `ops_pilot` imports, database/vector identifiers, OAuth scopes, cookies, webhook headers, workflow filenames, and existing environment variable names retain their established values for deployment compatibility.
