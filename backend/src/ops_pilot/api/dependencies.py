import uuid
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, Path, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ops_pilot.core.security import decode_access_token
from ops_pilot.db.session import get_db_session
from ops_pilot.models.membership import Membership, MembershipRole
from ops_pilot.models.user import User
from ops_pilot.services.email_verification import requires_email_verification

bearer_scheme = HTTPBearer()

DbSession = Annotated[AsyncSession, Depends(get_db_session)]


async def get_current_user(
    credentials: Annotated[
        HTTPAuthorizationCredentials,
        Depends(bearer_scheme),
    ],
    session: DbSession,
) -> User:
    credentials_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired authentication credentials",
    )

    try:
        payload = decode_access_token(credentials.credentials)
        subject = payload.get("sub")

        if subject is None:
            raise credentials_error

        user_id = uuid.UUID(subject)

    except (jwt.PyJWTError, ValueError) as exc:
        raise credentials_error from exc

    user = await session.get(User, user_id)

    if user is None or not user.is_active or payload.get('auth_ver', 0) != getattr(user, 'auth_version', 0):
        raise credentials_error

    if requires_email_verification(user):
        raise verification_required_error(user.email)

    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


async def get_current_membership(
    organization_id: Annotated[uuid.UUID, Path()],
    current_user: CurrentUser,
    session: DbSession,
) -> Membership:
    result = await session.execute(
        select(Membership).where(
            Membership.organization_id == organization_id,
            Membership.user_id == current_user.id,
        )
    )

    membership = result.scalar_one_or_none()

    if membership is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You do not have access to this organization",
        )

    return membership


CurrentMembership = Annotated[
    Membership,
    Depends(get_current_membership),
]


INCIDENT_CREATE_ROLES = frozenset(
    {
        MembershipRole.OWNER,
        MembershipRole.ADMIN,
        MembershipRole.OPERATOR,
    }
)

INCIDENT_INVESTIGATION_ROLES = frozenset(
    {
        MembershipRole.OWNER,
        MembershipRole.ADMIN,
        MembershipRole.OPERATOR,
        MembershipRole.REVIEWER,
    }
)

DOCUMENT_WRITE_ROLES = frozenset(
    {
        MembershipRole.OWNER,
        MembershipRole.ADMIN,
        MembershipRole.OPERATOR,
    }
)

APPROVAL_DECISION_ROLES = frozenset(
    {
        MembershipRole.OWNER,
        MembershipRole.ADMIN,
        MembershipRole.REVIEWER,
    }
)


def enforce_membership_role(
    membership: Membership,
    allowed_roles: frozenset[MembershipRole],
) -> Membership:
    """Enforce organization role before entering an endpoint."""

    if membership.role not in allowed_roles:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient organization permissions",
        )

    return membership


async def require_incident_creator(
    membership: CurrentMembership,
) -> Membership:
    return enforce_membership_role(
        membership,
        INCIDENT_CREATE_ROLES,
    )


async def require_incident_investigator(
    membership: CurrentMembership,
) -> Membership:
    return enforce_membership_role(
        membership,
        INCIDENT_INVESTIGATION_ROLES,
    )


async def require_document_writer(
    membership: CurrentMembership,
) -> Membership:
    return enforce_membership_role(
        membership,
        DOCUMENT_WRITE_ROLES,
    )


async def require_approval_reviewer(
    membership: CurrentMembership,
) -> Membership:
    if membership.role not in APPROVAL_DECISION_ROLES:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Approval decisions require reviewer, admin, or owner role",
        )

    return membership


IncidentCreatorMembership = Annotated[
    Membership,
    Depends(require_incident_creator),
]

IncidentInvestigatorMembership = Annotated[
    Membership,
    Depends(require_incident_investigator),
]

DocumentWriterMembership = Annotated[
    Membership,
    Depends(require_document_writer),
]

ApprovalReviewerMembership = Annotated[
    Membership,
    Depends(require_approval_reviewer),
]


def verification_required_error(email: str) -> HTTPException:
    return HTTPException(
        status_code=403,
        detail={
            "code": "email_verification_required",
            "message": (
                "Verify your email address before accessing your workspace or connecting an AI app."
            ),
            "email": email,
        },
    )
