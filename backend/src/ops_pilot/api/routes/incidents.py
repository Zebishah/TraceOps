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
from ops_pilot.schemas.approval_resume_status import (
    ApprovalResumeStatusResponse,
)
from ops_pilot.schemas.approvals import (
    ApprovalDecisionRequest,
    ApprovalResponse,
)
from ops_pilot.schemas.incidents import (
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
