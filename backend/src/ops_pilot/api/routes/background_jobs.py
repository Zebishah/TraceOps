import uuid

from fastapi import (
    APIRouter,
    HTTPException,
    status,
)

from ops_pilot.api.dependencies import (
    CurrentMembership,
    DbSession,
)
from ops_pilot.schemas.background_jobs import (
    BackgroundJobResponse,
)
from ops_pilot.services.background_jobs import (
    get_background_job,
)

router = APIRouter(
    prefix="/organizations/{organization_id}/jobs",
)


@router.get(
    "/{job_id}",
    response_model=BackgroundJobResponse,
)
async def get_background_job_endpoint(
    organization_id: uuid.UUID,
    job_id: uuid.UUID,
    membership: CurrentMembership,
    session: DbSession,
) -> BackgroundJobResponse:
    job = await get_background_job(
        session=session,
        organization_id=organization_id,
        job_id=job_id,
    )

    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Background job not found",
        )

    return BackgroundJobResponse.model_validate(
        job,
    )
