from fastapi import FastAPI

from ops_pilot.api.router import api_router
from ops_pilot.core.config import get_settings


def create_app() -> FastAPI:
    settings = get_settings()

    application = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
    )

    application.include_router(
        api_router,
        prefix="/api/v1",
    )

    return application


app = create_app()
