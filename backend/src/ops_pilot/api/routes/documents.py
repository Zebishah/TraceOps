import uuid
from typing import Annotated

from fastapi import APIRouter, File, UploadFile, status

from ops_pilot.api.dependencies import (
    CurrentMembership,
    CurrentUser,
    DbSession,
    DocumentWriterMembership,
)
from ops_pilot.schemas.background_jobs import BackgroundJobResponse
from ops_pilot.schemas.chunks import DocumentChunk
from ops_pilot.schemas.documents import (
    DocumentResponse,
)
from ops_pilot.services.background_job_dispatch import (
    enqueue_document_processing,
    enqueue_document_reindex,
)
from ops_pilot.services.document_chunking import (
    prepare_document_chunks,
)
from ops_pilot.services.documents import create_document

router = APIRouter(prefix="/organizations/{organization_id}/documents")


@router.post(
    "",
    response_model=DocumentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_document(
    organization_id: uuid.UUID,
    current_user: CurrentUser,
    membership: DocumentWriterMembership,
    session: DbSession,
    file: Annotated[UploadFile, File()],
) -> DocumentResponse:
    document = await create_document(
        session=session,
        organization_id=organization_id,
        user_id=current_user.id,
        file=file,
    )

    return DocumentResponse(
        id=document.id,
        organization_id=document.organization_id,
        uploaded_by_user_id=document.uploaded_by_user_id,
        original_filename=document.original_filename,
        mime_type=document.mime_type,
        size_bytes=document.size_bytes,
        checksum_sha256=document.checksum_sha256,
        status=document.status,
        created_at=document.created_at,
        failure_reason=document.failure_reason,
    )


@router.post(
    "/{document_id}/process",
    response_model=BackgroundJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def process_uploaded_document(
    organization_id: uuid.UUID,
    document_id: uuid.UUID,
    current_user: CurrentUser,
    membership: DocumentWriterMembership,
    session: DbSession,
) -> BackgroundJobResponse:
    job = await enqueue_document_processing(
        session=session,
        organization_id=organization_id,
        user_id=current_user.id,
        document_id=document_id,
    )

    return BackgroundJobResponse.model_validate(job)


@router.get(
    "/{document_id}/chunks",
    response_model=list[DocumentChunk],
)
async def preview_document_chunks(
    organization_id: uuid.UUID,
    document_id: uuid.UUID,
    current_user: CurrentUser,
    membership: CurrentMembership,
    session: DbSession,
) -> list[DocumentChunk]:
    return await prepare_document_chunks(
        session=session,
        organization_id=organization_id,
        document_id=document_id,
    )


@router.post(
    "/{document_id}/index",
    response_model=BackgroundJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def index_uploaded_document(
    organization_id: uuid.UUID,
    document_id: uuid.UUID,
    current_user: CurrentUser,
    membership: DocumentWriterMembership,
    session: DbSession,
) -> BackgroundJobResponse:
    job = await enqueue_document_reindex(
        session=session,
        organization_id=organization_id,
        user_id=current_user.id,
        document_id=document_id,
    )

    return BackgroundJobResponse.model_validate(job)
