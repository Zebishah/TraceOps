import uuid
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, Path, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ops_pilot.core.security import decode_access_token
from ops_pilot.db.session import get_db_session
from ops_pilot.models.membership import Membership
from ops_pilot.models.user import User

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

    if user is None or not user.is_active:
        raise credentials_error

    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


async def get_current_membership(
    organization_id: Annotated[
        uuid.UUID,
        Path(),
    ],
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
