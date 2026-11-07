import uuid

import jwt
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ops_pilot.core.security import (
    decode_mcp_access_token,
)
from ops_pilot.models.membership import (
    Membership,
    MembershipRole,
)
from ops_pilot.models.organization import Organization
from ops_pilot.models.user import User
from ops_pilot.schemas.mcp_auth import (
    MCPAuthenticatedContext,
    MCPOrganizationSummary,
)
from ops_pilot.services.email_verification import requires_email_verification
from ops_pilot.services.mcp_token_revocation import (
    is_mcp_access_token_revoked,
)


class MCPAuthenticationError(Exception):
    pass


class MCPAuthorizationError(Exception):
    pass


async def _get_authenticated_mcp_user(
    *,
    session: AsyncSession,
    access_token: str,
) -> User:
    """Authenticate a live, non-revoked MCP access token."""

    try:
        payload = decode_mcp_access_token(access_token)

        subject = payload.get("sub")
        jti = payload.get("jti")

        if subject is None:
            raise MCPAuthenticationError("Access token does not contain a subject")

        if not isinstance(jti, str) or not jti.strip():
            raise MCPAuthenticationError("Access token does not contain a valid token ID")

        user_id = uuid.UUID(str(subject))

    except (jwt.PyJWTError, ValueError, TypeError) as exc:
        raise MCPAuthenticationError("Invalid or expired access token") from exc

    try:
        revoked = await is_mcp_access_token_revoked(jti=jti)
    except Exception as exc:
        # If the revocation store cannot be checked,
        # do not accept an unverified access token.
        raise MCPAuthenticationError("Unable to verify access token revocation") from exc

    if revoked:
        raise MCPAuthenticationError("Access token has been revoked")

    user = await session.get(User, user_id)

    if user is None or not user.is_active:
        raise MCPAuthenticationError("Authenticated user is not available")

    if requires_email_verification(user):
        raise MCPAuthenticationError("Verify your email address in TraceOps before connecting")

    return user


async def list_mcp_organizations(
    *,
    session: AsyncSession,
    access_token: str,
) -> list[MCPOrganizationSummary]:
    user = await _get_authenticated_mcp_user(
        session=session,
        access_token=access_token,
    )

    result = await session.execute(
        select(
            Membership,
            Organization,
        )
        .join(
            Organization,
            Organization.id == Membership.organization_id,
        )
        .where(
            Membership.user_id == user.id,
        )
        .order_by(
            Organization.name.asc(),
        )
    )

    rows = result.all()

    return [
        MCPOrganizationSummary(
            id=organization.id,
            name=organization.name,
            slug=organization.slug,
            role=membership.role,
        )
        for membership, organization in rows
    ]


async def authenticate_mcp_access(
    *,
    session: AsyncSession,
    access_token: str,
    organization_id: uuid.UUID | None = None,
) -> MCPAuthenticatedContext:
    user = await _get_authenticated_mcp_user(
        session=session,
        access_token=access_token,
    )

    query = select(
        Membership,
    ).where(
        Membership.user_id == user.id,
    )

    if organization_id is not None:
        query = query.where(
            Membership.organization_id == organization_id,
        )

    result = await session.execute(
        query,
    )

    memberships = list(result.scalars().all())

    if organization_id is not None:
        if not memberships:
            raise MCPAuthorizationError("User does not have access to this organization")

        membership = memberships[0]

    else:
        if not memberships:
            raise MCPAuthorizationError("User does not belong to an organization")

        if len(memberships) > 1:
            raise MCPAuthorizationError(
                "Multiple organizations are available. "
                "Call list_my_organizations and provide organization_id."
            )

        membership = memberships[0]

    return MCPAuthenticatedContext(
        user_id=user.id,
        organization_id=membership.organization_id,
        role=membership.role,
    )


def require_mcp_investigation_role(
    context: MCPAuthenticatedContext,
) -> None:
    allowed_roles = {
        MembershipRole.OWNER,
        MembershipRole.ADMIN,
        MembershipRole.OPERATOR,
        MembershipRole.REVIEWER,
    }

    if context.role not in allowed_roles:
        raise MCPAuthorizationError("User role cannot start incident investigations")
