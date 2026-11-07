# IncidentIQ Backend

Python/FastAPI API for IncidentIQ's multi-tenant investigations, knowledge retrieval, approvals, background jobs, and MCP tools.

## Development

Run these commands from `backend/`:

```bash
cp .env.example .env
uv sync
```

Configure the database and provider settings in `.env`, then run:

```bash
uv run alembic upgrade head
uv run uvicorn ops_pilot.main:app --reload --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000/docs` for the API reference. Run durable jobs through the configured Inngest integration; n8n must be reachable for external automation delivery.

## Checks

```bash
uv run ruff check .
uv run mypy
uv run pytest
```

See the [project README](../README.md), [architecture](../docs/architecture.md), and [environment template](.env.example) for the full setup and integration boundaries. The Python package remains `ops_pilot` for compatibility. Optional fine-tuning dependencies live separately under `finetuning/`.
