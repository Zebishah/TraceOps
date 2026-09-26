from fastapi import APIRouter

from ops_pilot.api.routes.auth import router as auth_router
from ops_pilot.api.routes.health import router as health_router

api_router = APIRouter()

api_router.include_router(
    health_router,
    tags=["health"],
)
api_router.include_router(
    auth_router,
    tags=["auth"],
)
