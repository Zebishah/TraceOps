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
from ops_pilot.models.user import User
from ops_pilot.schemas.mcp_auth import (
    MCPAuthenticatedContext,
)


class MCPAuthenticationError(Exception):
    pass


class MCPAuthorizationError(Exception):
    pass


async def authenticate_mcp_access(
    *,
    session: AsyncSession,
    access_token: str,
    organization_id: uuid.UUID,
) -> MCPAuthenticatedContext:
    try:
        payload = decode_mcp_access_token(
            access_token,
        )

        subject = payload.get("sub")

        if subject is None:
            raise MCPAuthenticationError("Access token does not contain a subject")

        user_id = uuid.UUID(
            str(subject),
        )

    except (
        jwt.PyJWTError,
        ValueError,
    ) as exc:
        raise MCPAuthenticationError("Invalid or expired access token") from exc

    user = await session.get(
        User,
        user_id,
    )

    if user is None or not user.is_active:
        raise MCPAuthenticationError("Authenticated user is not available")

    result = await session.execute(
        select(Membership).where(
            Membership.organization_id == organization_id,
            Membership.user_id == user_id,
        )
    )

    membership = result.scalar_one_or_none()

    if membership is None:
        raise MCPAuthorizationError("User does not have access to this organization")

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
