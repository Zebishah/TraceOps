import uuid

from fastapi import APIRouter

from ops_pilot.api.dependencies import CurrentMembership
from ops_pilot.schemas.retrieval import (
    RetrievalRequest,
    RetrievalResponse,
)
from ops_pilot.services.retrieval import (
    retrieve_document_chunks,
)

router = APIRouter(
    prefix="/organizations/{organization_id}/retrieval",
    tags=["retrieval"],
)


@router.post(
    "/search",
    response_model=RetrievalResponse,
)
async def semantic_search(
    organization_id: uuid.UUID,
    request: RetrievalRequest,
    membership: CurrentMembership,
) -> RetrievalResponse:
    results = await retrieve_document_chunks(
        organization_id=organization_id,
        query=request.query,
        limit=request.limit,
    )

    return RetrievalResponse(
        query=request.query,
        results=results,
    )
