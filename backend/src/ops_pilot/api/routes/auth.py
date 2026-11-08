from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import select

from ops_pilot.api.dependencies import CurrentUser, DbSession, verification_required_error
from ops_pilot.core.config import get_settings
from ops_pilot.core.security import (
    create_access_token,
    create_mcp_access_token,
)
from ops_pilot.models.membership import Membership
from ops_pilot.schemas.auth import (
    EmailCodeVerifiedResponse,
    EmailVerifiedResponse,
    LoginRequest,
    MembershipResponse,
    MeResponse,
    PasswordResetConfirm,
    PasswordResetRequest,
    RegisterRequest,
    TokenResponse,
    UserResponse,
    VerificationEmailRequest,
    VerificationMessage,
    VerifyEmailCodeRequest,
    VerifyEmailRequest,
)
from ops_pilot.services.auth import (
    authenticate_user,
    get_user_by_email,
    register_user,
)
from ops_pilot.services.auth_rate_limit import (
    AuthRateLimitExceeded,
    AuthRateLimitUnavailable,
    enforce_login_rate_limit,
    enforce_registration_rate_limit,
    enforce_verification_claim_limit,
    enforce_verification_request_limit,
)
from ops_pilot.services.email_verification import (
    issue_verification_code,
    requires_email_verification,
    verify_email_code,
    verify_email_token,
)
from ops_pilot.services.password_recovery import confirm_password_reset, request_password_reset


def _no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"
    response.headers["Referrer-Policy"] = "no-referrer"


router = APIRouter(prefix="/auth", dependencies=[Depends(_no_store)])


def _raise_rate_limit_error(
    exc: AuthRateLimitExceeded | AuthRateLimitUnavailable,
) -> None:
    if isinstance(exc, AuthRateLimitExceeded):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many requests. Please try again later.",
            headers={
                "Retry-After": str(exc.retry_after_seconds),
            },
        ) from exc

    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Authentication temporarily unavailable",
    ) from exc


@router.post(
    "/register",
    response_model=UserResponse,
    status_code=status.HTTP_201_CREATED,
)
async def register(
    payload: RegisterRequest,
    session: DbSession,
    request: Request,
) -> UserResponse:
    try:
        await enforce_registration_rate_limit(
            request=request,
        )
    except (AuthRateLimitExceeded, AuthRateLimitUnavailable) as exc:
        _raise_rate_limit_error(exc)

    user = await register_user(
        session,
        payload,
    )

    required = requires_email_verification(user)
    sent = await issue_verification_code(session, user) if required else False

    return UserResponse(
        email_verified=user.email_verified_at is not None,
        verification_required=required,
        verification_email_sent=sent,
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
    request: Request,
) -> TokenResponse:
    try:
        await enforce_login_rate_limit(
            request=request,
            email=payload.email,
        )
    except (AuthRateLimitExceeded, AuthRateLimitUnavailable) as exc:
        _raise_rate_limit_error(exc)

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

    if requires_email_verification(user):
        try:
            await enforce_verification_request_limit(request=request, email=user.email)
        except (AuthRateLimitExceeded, AuthRateLimitUnavailable) as exc:
            _raise_rate_limit_error(exc)
        sent = await issue_verification_code(session, user)
        error = verification_required_error(user.email)
        error.detail["verification_email_sent"] = sent
        raise error

    token = create_access_token(
        subject=str(user.id),
        auth_version=getattr(user, "auth_version", 0),
    )

    return TokenResponse(
        access_token=token,
    )


@router.post(
    "/mcp-token",
    response_model=TokenResponse,
)
async def create_mcp_token(
    current_user: CurrentUser,
) -> TokenResponse:
    token = create_mcp_access_token(
        subject=str(current_user.id),
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
    result = await session.execute(
        select(Membership).where(
            Membership.user_id == current_user.id,
        )
    )

    memberships = result.scalars().all()

    return MeResponse(
        user=UserResponse(
            id=current_user.id,
            email=current_user.email,
            full_name=current_user.full_name,
            is_active=current_user.is_active,
            email_verified=current_user.email_verified_at is not None,
            verification_required=requires_email_verification(current_user),
        ),
        memberships=[
            MembershipResponse(
                organization_id=membership.organization_id,
                role=membership.role,
            )
            for membership in memberships
        ],
    )


@router.post("/verification/request", response_model=VerificationMessage)
async def request_email_verification(
    payload: VerificationEmailRequest,
    session: DbSession,
    request: Request,
) -> VerificationMessage:
    if not get_settings().email_verification_enabled:
        raise HTTPException(status_code=503, detail="Email verification is not enabled")
    try:
        await enforce_verification_request_limit(request=request, email=payload.email)
    except (AuthRateLimitExceeded, AuthRateLimitUnavailable) as exc:
        _raise_rate_limit_error(exc)
    user = await get_user_by_email(session, payload.email)
    if user is not None:
        await issue_verification_code(session, user)
    # Same response for unknown, verified, disabled and delivery-failed accounts.
    return VerificationMessage(
        message="If this address belongs to an account awaiting verification, "
        "a six-digit code will be sent. Check your inbox and spam folder.",
    )


@router.post("/verification/confirm", response_model=EmailVerifiedResponse)
async def confirm_email_verification(
    payload: VerifyEmailRequest,
    session: DbSession,
    request: Request,
) -> EmailVerifiedResponse:
    if not get_settings().email_verification_enabled:
        raise HTTPException(status_code=503, detail="Email verification is not enabled")
    try:
        await enforce_verification_claim_limit(request=request)
    except (AuthRateLimitExceeded, AuthRateLimitUnavailable) as exc:
        _raise_rate_limit_error(exc)
    if not await verify_email_token(session, payload.token):
        raise HTTPException(
            status_code=400,
            detail="This verification link is invalid, expired, or already used. "
            "Try signing in if you already verified, or sign in to receive a new code.",
        )
    return EmailVerifiedResponse()


@router.post("/verification/code", response_model=EmailCodeVerifiedResponse)
async def confirm_email_code(
    payload: VerifyEmailCodeRequest,
    session: DbSession,
    request: Request,
) -> EmailCodeVerifiedResponse:
    if not get_settings().email_verification_enabled:
        raise HTTPException(status_code=503, detail="Email verification is not enabled")
    try:
        await enforce_verification_claim_limit(request=request, email=payload.email)
    except (AuthRateLimitExceeded, AuthRateLimitUnavailable) as exc:
        _raise_rate_limit_error(exc)
    user = await verify_email_code(session, payload.email, payload.code)
    if user is None:
        raise HTTPException(
            status_code=400,
            detail="This code is incorrect or expired. Check the code in your email or resend it.",
        )
    return EmailCodeVerifiedResponse(
        access_token=create_access_token(
            subject=str(user.id), auth_version=getattr(user, "auth_version", 0)
        )
    )


@router.post("/password-reset/request", response_model=VerificationMessage)
async def password_reset_request(
    payload: PasswordResetRequest,
    session: DbSession,
    request: Request,
) -> VerificationMessage:
    try:
        await enforce_verification_request_limit(request=request, email=str(payload.email))
    except (AuthRateLimitExceeded, AuthRateLimitUnavailable) as exc:
        _raise_rate_limit_error(exc)
    await request_password_reset(session, str(payload.email))
    return VerificationMessage(
        message="If an eligible account exists, you will receive a password reset link."
    )


@router.post("/password-reset/confirm", response_model=VerificationMessage)
async def password_reset_confirm(
    payload: PasswordResetConfirm,
    session: DbSession,
    request: Request,
) -> VerificationMessage:
    try:
        await enforce_verification_claim_limit(request=request)
    except (AuthRateLimitExceeded, AuthRateLimitUnavailable) as exc:
        _raise_rate_limit_error(exc)
    if not await confirm_password_reset(session, payload.token, payload.password):
        raise HTTPException(
            status_code=400,
            detail="This reset link is invalid, expired, or has already been used.",
        )
    return VerificationMessage(message="Password updated. Sign in with your new password.")
