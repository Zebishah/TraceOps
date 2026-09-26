from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from ops_pilot.api.dependencies import CurrentUser, DbSession
from ops_pilot.core.security import create_access_token
from ops_pilot.models.membership import Membership
from ops_pilot.schemas.auth import (
    LoginRequest,
    MembershipResponse,
    MeResponse,
    RegisterRequest,
    TokenResponse,
    UserResponse,
)
from ops_pilot.services.auth import (
    EmailAlreadyRegisteredError,
    OrganizationSlugAlreadyExistsError,
    RegistrationConflictError,
    authenticate_user,
    register_user,
)

router = APIRouter(prefix="/auth")


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
)
@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
)
async def register(
    payload: RegisterRequest,
    session: DbSession,
) -> UserResponse:
    try:
        user = await register_user(
            session,
            payload,
        )

    except EmailAlreadyRegisteredError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Email already registered",
        ) from exc

    except OrganizationSlugAlreadyExistsError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Organization slug already exists",
        ) from exc

    except RegistrationConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Registration conflicts with existing data",
        ) from exc

    return UserResponse(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        is_active=user.is_active,
    )


@router.post(
    "/login",
    response_model=TokenResponse,
)
async def login(
    payload: LoginRequest,
    session: DbSession,
) -> TokenResponse:
    user = await authenticate_user(
        session,
        payload.email,
        payload.password,
    )

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password",
        )

    token = create_access_token(
        subject=str(user.id),
    )

    return TokenResponse(
        access_token=token,
    )


@router.get(
    "/me",
    response_model=MeResponse,
)
async def me(
    current_user: CurrentUser,
    session: DbSession,
) -> MeResponse:
    result = await session.execute(select(Membership).where(Membership.user_id == current_user.id))

    memberships = result.scalars().all()

    return MeResponse(
        user=UserResponse(
            id=current_user.id,
            email=current_user.email,
            full_name=current_user.full_name,
            is_active=current_user.is_active,
        ),
        memberships=[
            MembershipResponse(
                organization_id=membership.organization_id,
                role=membership.role,
            )
            for membership in memberships
        ],
    )
