import uuid

from fastapi import APIRouter, HTTPException, Query, status

from ops_pilot.api.dependencies import (
    ApprovalReviewerMembership,
    CurrentMembership,
    CurrentUser,
    DbSession,
    IncidentCreatorMembership,
    IncidentInvestigatorMembership,
)
from ops_pilot.models.background_job import (
    BackgroundJobStatus,
    BackgroundJobType,
)
from ops_pilot.schemas.approval_resume_status import (
    ApprovalResumeStatusResponse,
)
from ops_pilot.schemas.approvals import (
    ApprovalDecisionRequest,
    ApprovalResponse,
)
from ops_pilot.schemas.background_jobs import BackgroundJobResponse
from ops_pilot.schemas.incidents import (
    IncidentAcknowledgmentResponse,
    IncidentClassificationResponse,
    IncidentCreateRequest,
    IncidentEvidenceResponse,
    IncidentInvestigationResponse,
    IncidentNoActionResolutionRequest,
    IncidentResponse,
)
from ops_pilot.services.approval_resume_status import (
    get_approval_resume_status,
)
from ops_pilot.services.approval_workflow import (
    decide_and_resume_approval,
)
from ops_pilot.services.approvals import get_approval_request
from ops_pilot.services.background_jobs import get_background_job
from ops_pilot.services.incident_acknowledgment import (
    IncidentAcknowledgmentConflict,
    IncidentAcknowledgmentNotFound,
    acknowledge_incident,
)
from ops_pilot.services.incident_background import (
    InvestigationRetryConflict,
    InvestigationRetryDispatchError,
    InvestigationRetryNotFound,
    enqueue_incident_analysis,
    get_incident_analysis_result,
    retry_incident_analysis,
)
from ops_pilot.services.incident_classification import (
    classify_stored_incident,
)
from ops_pilot.services.incident_evidence import (
    retrieve_incident_evidence,
)
from ops_pilot.services.incident_investigation import investigate_incident
from ops_pilot.services.incident_resolution import (
    IncidentResolutionConflict,
    IncidentResolutionNotFound,
    resolve_incident_without_action,
)
from ops_pilot.services.incidents import (
    create_incident,
    get_incident_response_cached,
    invalidate_incident_cache,
    list_incidents,
)

router = APIRouter(
    prefix="/organizations/{organization_id}/incidents",
)


@router.post(
    "",
    response_model=IncidentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_incident_endpoint(
    organization_id: uuid.UUID,
    payload: IncidentCreateRequest,
    current_user: CurrentUser,
    membership: IncidentCreatorMembership,
    session: DbSession,
) -> IncidentResponse:
    incident = await create_incident(
        session=session,
        organization_id=organization_id,
        user_id=current_user.id,
        payload=payload,
    )

    return IncidentResponse.model_validate(incident)


@router.get(
    "",
    response_model=list[IncidentResponse],
)
async def list_incidents_endpoint(
    organization_id: uuid.UUID,
    membership: CurrentMembership,
    session: DbSession,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> list[IncidentResponse]:
    incidents = await list_incidents(
        session=session,
        organization_id=organization_id,
        limit=limit,
        offset=offset,
    )

    return [IncidentResponse.model_validate(incident) for incident in incidents]


@router.get(
    "/{incident_id}",
    response_model=IncidentResponse,
)
async def get_incident_endpoint(
    organization_id: uuid.UUID,
    incident_id: uuid.UUID,
    membership: CurrentMembership,
    session: DbSession,
) -> IncidentResponse:
    return await get_incident_response_cached(
        session=session,
        organization_id=organization_id,
        incident_id=incident_id,
        force_fresh=True,
    )


@router.post(
    "/{incident_id}/classify",
    response_model=IncidentClassificationResponse,
)
async def classify_incident_endpoint(
    organization_id: uuid.UUID,
    incident_id: uuid.UUID,
    membership: IncidentInvestigatorMembership,
    session: DbSession,
) -> IncidentClassificationResponse:
    try:
        incident, classification = await classify_stored_incident(
            session=session,
            organization_id=organization_id,
            incident_id=incident_id,
        )
    except IncidentResolutionConflict as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc

    await invalidate_incident_cache(
        organization_id=organization_id,
        incident_id=incident_id,
    )

    return IncidentClassificationResponse(
        incident_id=incident.id,
        status=incident.status,
        category=classification.category,
        priority=classification.priority,
        confidence=classification.confidence,
    )


@router.post(
    "/{incident_id}/retrieve-evidence",
    response_model=IncidentEvidenceResponse,
)
async def retrieve_incident_evidence_endpoint(
    organization_id: uuid.UUID,
    incident_id: uuid.UUID,
    membership: IncidentInvestigatorMembership,
    session: DbSession,
) -> IncidentEvidenceResponse:
    query, evidence = await retrieve_incident_evidence(
        session=session,
        organization_id=organization_id,
        incident_id=incident_id,
    )

    return IncidentEvidenceResponse(
        incident_id=incident_id,
        query=query,
        evidence=evidence,
    )


@router.post(
    "/{incident_id}/investigate",
    response_model=IncidentInvestigationResponse,
)
async def investigate_incident_endpoint(
    organization_id: uuid.UUID,
    incident_id: uuid.UUID,
    membership: IncidentInvestigatorMembership,
    session: DbSession,
) -> IncidentInvestigationResponse:
    result = await investigate_incident(
        session=session,
        organization_id=organization_id,
        incident_id=incident_id,
    )

    await invalidate_incident_cache(
        organization_id=organization_id,
        incident_id=incident_id,
    )

    return result


@router.get(
    "/{incident_id}/approvals/{approval_request_id}",
    response_model=ApprovalResponse,
)
async def get_approval_request_endpoint(
    organization_id: uuid.UUID,
    incident_id: uuid.UUID,
    approval_request_id: uuid.UUID,
    membership: CurrentMembership,
    session: DbSession,
) -> ApprovalResponse:
    approval = await get_approval_request(
        session=session,
        organization_id=organization_id,
        incident_id=incident_id,
        approval_request_id=approval_request_id,
    )

    return ApprovalResponse.model_validate(approval)


@router.post(
    "/{incident_id}/approvals/{approval_request_id}/decision",
    response_model=ApprovalResponse,
)
async def decide_approval_endpoint(
    organization_id: uuid.UUID,
    incident_id: uuid.UUID,
    approval_request_id: uuid.UUID,
    payload: ApprovalDecisionRequest,
    current_user: CurrentUser,
    membership: ApprovalReviewerMembership,
    session: DbSession,
) -> ApprovalResponse:
    approval = await decide_and_resume_approval(
        session=session,
        organization_id=organization_id,
        incident_id=incident_id,
        approval_request_id=approval_request_id,
        decided_by_user_id=current_user.id,
        payload=payload,
    )

    await invalidate_incident_cache(
        organization_id=organization_id,
        incident_id=incident_id,
    )

    return ApprovalResponse.model_validate(approval)


@router.post(
    "/{incident_id}/resolve-no-action",
    response_model=IncidentResponse,
)
async def resolve_no_action_endpoint(
    organization_id: uuid.UUID,
    incident_id: uuid.UUID,
    payload: IncidentNoActionResolutionRequest,
    current_user: CurrentUser,
    membership: ApprovalReviewerMembership,
    session: DbSession,
) -> IncidentResponse:
    try:
        incident = await resolve_incident_without_action(
            session=session,
            organization_id=organization_id,
            incident_id=incident_id,
            resolved_by_user_id=current_user.id,
            reason=payload.reason,
            **(
                {
                    "outcome": payload.outcome,
                    "customer_message": payload.customer_message,
                    "next_steps": payload.next_steps,
                }
                if payload.outcome is not None
                else {}
            ),
        )
    except IncidentResolutionNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except IncidentResolutionConflict as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc

    await invalidate_incident_cache(
        organization_id=organization_id,
        incident_id=incident_id,
    )

    return IncidentResponse.model_validate(incident)


@router.get(
    "/{incident_id}/approvals/{approval_request_id}/resume-status",
    response_model=ApprovalResumeStatusResponse,
)
async def get_approval_resume_status_endpoint(
    organization_id: uuid.UUID,
    incident_id: uuid.UUID,
    approval_request_id: uuid.UUID,
    membership: CurrentMembership,
    session: DbSession,
) -> ApprovalResumeStatusResponse:
    result = await get_approval_resume_status(
        session=session,
        organization_id=organization_id,
        incident_id=incident_id,
        approval_request_id=approval_request_id,
    )

    if result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Approval recovery job not found",
        )

    return result


@router.post(
    "/{incident_id}/acknowledge",
    response_model=IncidentAcknowledgmentResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def acknowledge_incident_endpoint(
    organization_id: uuid.UUID,
    incident_id: uuid.UUID,
    current_user: CurrentUser,
    membership: IncidentInvestigatorMembership,
    session: DbSession,
) -> IncidentAcknowledgmentResponse:
    try:
        event_id = await acknowledge_incident(
            session=session,
            organization_id=organization_id,
            incident_id=incident_id,
            responder_id=current_user.id,
        )

    except IncidentAcknowledgmentNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc

    except IncidentAcknowledgmentConflict as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc

    return IncidentAcknowledgmentResponse(
        incident_id=incident_id,
        event_id=event_id,
        status="queued",
    )


@router.post(
    "/{incident_id}/investigate-background",
    response_model=BackgroundJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def enqueue_incident_investigation_endpoint(
    organization_id: uuid.UUID,
    incident_id: uuid.UUID,
    current_user: CurrentUser,
    membership: IncidentInvestigatorMembership,
    session: DbSession,
) -> BackgroundJobResponse:
    try:
        job = await enqueue_incident_analysis(
            session=session,
            organization_id=organization_id,
            incident_id=incident_id,
            user_id=current_user.id,
        )
    except IncidentResolutionConflict as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc

    return BackgroundJobResponse.model_validate(job)


@router.get(
    "/{incident_id}/investigations/{job_id}/result",
    response_model=IncidentInvestigationResponse,
)
async def get_background_investigation_result_endpoint(
    organization_id: uuid.UUID,
    incident_id: uuid.UUID,
    job_id: uuid.UUID,
    membership: IncidentInvestigatorMembership,
    session: DbSession,
) -> IncidentInvestigationResponse:
    job = await get_background_job(
        session=session,
        organization_id=organization_id,
        job_id=job_id,
    )

    if (
        job is None
        or job.job_type != BackgroundJobType.INCIDENT_ANALYSIS
        or job.resource_id != incident_id
    ):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Investigation job not found",
        )

    if job.status != BackgroundJobStatus.SUCCEEDED:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Investigation result is not ready",
        )

    # Release the read transaction before loading checkpoints.
    await session.rollback()

    return await get_incident_analysis_result(
        organization_id=organization_id,
        incident_id=incident_id,
        job_id=job_id,
    )


@router.post(
    "/{incident_id}/investigations/{job_id}/retry",
    response_model=BackgroundJobResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def retry_background_investigation_endpoint(
    organization_id: uuid.UUID,
    incident_id: uuid.UUID,
    job_id: uuid.UUID,
    current_user: CurrentUser,
    membership: IncidentInvestigatorMembership,
    session: DbSession,
) -> BackgroundJobResponse:
    try:
        job = await retry_incident_analysis(
            session=session,
            organization_id=organization_id,
            incident_id=incident_id,
            job_id=job_id,
            requested_by_user_id=current_user.id,
        )
    except InvestigationRetryNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except InvestigationRetryConflict as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    except InvestigationRetryDispatchError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=str(exc),
        ) from exc

    return BackgroundJobResponse.model_validate(job)
