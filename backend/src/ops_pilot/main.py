from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import inngest.fast_api
from fastapi import FastAPI

from ops_pilot.ai.embeddings import close_mistral_embedding_client
from ops_pilot.ai.reranker import close_voyage_reranker_client
from ops_pilot.api.exception_handlers import register_exception_handlers
from ops_pilot.api.router import api_router
from ops_pilot.cache.redis import close_redis_client
from ops_pilot.core.config import get_settings
from ops_pilot.inngest.client import inngest_client
from ops_pilot.inngest.functions.document_processing import (
    process_document_background,
)
from ops_pilot.inngest.functions.health import (
    background_health_check,
)
from ops_pilot.inngest.functions.memory_indexing import (
    index_incident_memory_background,
)
from ops_pilot.mcp.http import mcp_http_app
from ops_pilot.mcp.server import mcp
from ops_pilot.vectorstore.qdrant import close_qdrant_client


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    async with mcp.session_manager.run():
        yield

    await close_redis_client()
    await close_mistral_embedding_client()
    await close_voyage_reranker_client()
    await close_qdrant_client()


def create_app() -> FastAPI:
    settings = get_settings()

    application = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        lifespan=lifespan,
    )
    inngest.fast_api.serve(
        application,
        inngest_client,
        [background_health_check, process_document_background, index_incident_memory_background],
    )
    register_exception_handlers(
        application,
    )

    application.include_router(
        api_router,
        prefix="/api/v1",
    )
    application.mount(
        "/",
        mcp_http_app,
    )
    return application


app = create_app()
