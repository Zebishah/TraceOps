from fastapi import APIRouter

from ops_pilot.api.routes.dashboard import router as dashboard_router

from ops_pilot.api.routes.answers import router as answers_router
from ops_pilot.api.routes.auth import router as auth_router
from ops_pilot.api.routes.background_jobs import (
    router as background_jobs_router,
)
from ops_pilot.api.routes.documents import router as documents_router
from ops_pilot.api.routes.health import router as health_router
from ops_pilot.api.routes.incidents import router as incidents_router
from ops_pilot.api.routes.retrieval import router as retrieval_router

api_router = APIRouter()

api_router.include_router(
    health_router,
    tags=["health"],
)
api_router.include_router(
    auth_router,
    tags=["auth"],
)
api_router.include_router(
    documents_router,
    tags=["documents"],
)
api_router.include_router(
    retrieval_router,
    tags=["retrieval"],
)
api_router.include_router(
    answers_router,
    tags=["answers"],
)
api_router.include_router(
    incidents_router,
    tags=["incidents"],
)
api_router.include_router(
    background_jobs_router,
    tags=["background-jobs"],
)

api_router.include_router(dashboard_router)

