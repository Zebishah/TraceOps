from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import inngest
import inngest.fast_api
from fastapi import FastAPI

from ops_pilot.ai.embeddings import close_mistral_embedding_client
from ops_pilot.ai.reranker import close_voyage_reranker_client
from ops_pilot.api.exception_handlers import register_exception_handlers
from ops_pilot.api.request_context import (
    RequestContextMiddleware,
)
from ops_pilot.api.router import api_router
from ops_pilot.api.training_limit import TrainingBodyLimitMiddleware
from ops_pilot.api.upload_limit import DocumentUploadLimitMiddleware
from ops_pilot.api.voice_limit import VoiceBodyLimitMiddleware
from ops_pilot.cache.redis import close_redis_client
from ops_pilot.core.config import get_settings
from ops_pilot.core.logging import configure_logging
from ops_pilot.db.engine import engine
from ops_pilot.inngest.client import inngest_client
from ops_pilot.inngest.functions.approval_resume_recovery import recover_approval_resume_jobs
from ops_pilot.inngest.functions.automation_delivery_recovery import (
    recover_automation_deliveries_background,
)
from ops_pilot.inngest.functions.dispatch_recovery import (
    recover_background_dispatches,
)
from ops_pilot.inngest.functions.document_processing import (
    process_document_background,
)
from ops_pilot.inngest.functions.health import (
    background_health_check,
)
from ops_pilot.inngest.functions.incident_analysis import (
    investigate_incident_background,
)
from ops_pilot.inngest.functions.memory_indexing import (
    index_incident_memory_background,
)
from ops_pilot.mcp.http import mcp_http_app
from ops_pilot.mcp.oauth_http import (
    build_oauth_routes,
)
from ops_pilot.mcp.server import mcp
from ops_pilot.vectorstore.qdrant import close_qdrant_client


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    try:
        async with mcp.session_manager.run():
            yield
    finally:
        try:
            await close_redis_client()
        finally:
            try:
                await close_mistral_embedding_client()
            finally:
                try:
                    await close_voyage_reranker_client()
                finally:
                    try:
                        await close_qdrant_client()
                    finally:
                        await engine.dispose()


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(
        level=settings.log_level,
    )
    application = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        lifespan=lifespan,
    )
    application.add_middleware(RequestContextMiddleware)
    application.add_middleware(DocumentUploadLimitMiddleware)
    application.add_middleware(VoiceBodyLimitMiddleware)
    application.add_middleware(TrainingBodyLimitMiddleware)
    inngest_functions: list[inngest.Function[Any]] = [
        background_health_check,
        process_document_background,
        index_incident_memory_background,
        recover_background_dispatches,
        recover_automation_deliveries_background,
        investigate_incident_background,
    ]

    # Financial recovery is intentionally opt-in.
    # Production must never register this scheduler
    # through the staging feature switch.
    environment = settings.environment.lower()

    register_approval_recovery = (
        environment == "staging" and settings.enable_approval_resume_cron
    ) or (environment == "production" and settings.enable_production_approval_recovery)

    if register_approval_recovery:
        inngest_functions.append(recover_approval_resume_jobs)

    inngest.fast_api.serve(
        application,
        inngest_client,
        inngest_functions,
    )

    register_exception_handlers(
        application,
    )

    application.include_router(
        api_router,
        prefix="/api/v1",
    )
    application.router.routes.extend(build_oauth_routes())

    @application.get("/")
    async def root() -> dict[str, str]:
        return {"status": "ok"}

    application.mount(
        "/",
        mcp_http_app,
    )
    return application


app = create_app()
