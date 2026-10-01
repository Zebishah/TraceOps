import uuid

from fastapi import (
    APIRouter,
    HTTPException,
    status,
)

from ops_pilot.api.dependencies import (
    CurrentMembership,
    CurrentUser,
    DbSession,
)
from ops_pilot.models.membership import MembershipRole
from ops_pilot.schemas.approvals import (
    ApprovalDecisionRequest,
    ApprovalResponse,
)
from ops_pilot.schemas.incidents import (
    IncidentClassificationResponse,
    IncidentCreateRequest,
    IncidentEvidenceResponse,
    IncidentInvestigationResponse,
    IncidentResponse,
)
from ops_pilot.services.approval_workflow import (
    decide_and_resume_approval,
)
from ops_pilot.services.approvals import (
    get_approval_request,
)
from ops_pilot.services.incident_classification import (
    classify_stored_incident,
)
from ops_pilot.services.incident_evidence import (
    retrieve_incident_evidence,
)
from ops_pilot.services.incident_investigation import investigate_incident
from ops_pilot.services.incidents import (
    create_incident,
    get_incident,
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
    membership: CurrentMembership,
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
) -> list[IncidentResponse]:
    incidents = await list_incidents(
        session=session,
        organization_id=organization_id,
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
    incident = await get_incident(
        session=session,
        organization_id=organization_id,
        incident_id=incident_id,
    )

    return IncidentResponse.model_validate(incident)


@router.post(
    "/{incident_id}/classify",
    response_model=IncidentClassificationResponse,
)
async def classify_incident_endpoint(
    organization_id: uuid.UUID,
    incident_id: uuid.UUID,
    membership: CurrentMembership,
    session: DbSession,
) -> IncidentClassificationResponse:
    incident, classification = await classify_stored_incident(
        session=session,
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
    membership: CurrentMembership,
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
    membership: CurrentMembership,
    session: DbSession,
) -> IncidentInvestigationResponse:
    return await investigate_incident(
        session=session,
        organization_id=organization_id,
        incident_id=incident_id,
    )


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

    return ApprovalResponse.model_validate(
        approval,
    )


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
    membership: CurrentMembership,
    session: DbSession,
) -> ApprovalResponse:
    allowed_roles = {
        MembershipRole.OWNER,
        MembershipRole.ADMIN,
        MembershipRole.REVIEWER,
    }

    if membership.role not in allowed_roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=("Approval decisions require reviewer, admin, or owner role"),
        )

    approval = await decide_and_resume_approval(
        session=session,
        organization_id=organization_id,
        incident_id=incident_id,
        approval_request_id=approval_request_id,
        decided_by_user_id=current_user.id,
        payload=payload,
    )

    return ApprovalResponse.model_validate(
        approval,
    )
