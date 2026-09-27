from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from ops_pilot.core.exceptions import (
    DocumentNotFoundError,
    DocumentProcessingError,
    DocumentTooLargeError,
    DocumentUploadError,
    EmailAlreadyRegisteredError,
    OrganizationSlugAlreadyExistsError,
    RegistrationConflictError,
    UnsupportedDocumentTypeError,
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


async def unsupported_document_type_handler(
    request: Request,
    exc: Exception,
) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
        content={
            "detail": "Unsupported document type",
        },
    )


async def document_too_large_handler(
    request: Request,
    exc: Exception,
) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
        content={
            "detail": "Document is too large",
        },
    )


async def document_upload_handler(
    request: Request,
    exc: Exception,
) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "detail": "Document upload failed",
        },
    )


async def document_not_found_handler(
    request: Request,
    exc: Exception,
) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_404_NOT_FOUND,
        content={
            "detail": "Document not found",
        },
    )


async def document_processing_handler(
    request: Request,
    exc: Exception,
) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "detail": "Document processing failed",
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

    app.add_exception_handler(
        UnsupportedDocumentTypeError,
        unsupported_document_type_handler,
    )

    app.add_exception_handler(
        DocumentTooLargeError,
        document_too_large_handler,
    )

    app.add_exception_handler(
        DocumentUploadError,
        document_upload_handler,
    )
    app.add_exception_handler(
        DocumentNotFoundError,
        document_not_found_handler,
    )

    app.add_exception_handler(
        DocumentProcessingError,
        document_processing_handler,
    )
