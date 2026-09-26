from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from ops_pilot.core.exceptions import (
    EmailAlreadyRegisteredError,
    OrganizationSlugAlreadyExistsError,
    RegistrationConflictError,
)


async def email_already_registered_handler(
    request: Request,
    exc: Exception,
) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_409_CONFLICT,
        content={
            "detail": "Email already registered",
        },
    )


async def organization_slug_exists_handler(
    request: Request,
    exc: Exception,
) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_409_CONFLICT,
        content={
            "detail": "Organization slug already exists",
        },
    )


async def registration_conflict_handler(
    request: Request,
    exc: Exception,
) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_409_CONFLICT,
        content={
            "detail": "Registration conflicts with existing data",
        },
    )


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(
        EmailAlreadyRegisteredError,
        email_already_registered_handler,
    )

    app.add_exception_handler(
        OrganizationSlugAlreadyExistsError,
        organization_slug_exists_handler,
    )

    app.add_exception_handler(
        RegistrationConflictError,
        registration_conflict_handler,
    )
