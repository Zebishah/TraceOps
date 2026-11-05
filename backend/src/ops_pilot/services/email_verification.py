"""Mailbox verification is independent from login sessions and MCP authorization codes."""

import hashlib
import logging
import re
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ops_pilot.core.config import get_settings
from ops_pilot.models.email_verification_token import EmailVerificationToken
from ops_pilot.models.user import User
from ops_pilot.services.auth_rate_limit import (
    AuthRateLimitExceeded,
    AuthRateLimitUnavailable,
    enforce_verification_delivery_limit,
)
from ops_pilot.services.transactional_email import EmailDeliveryError, send_verification_email

logger = logging.getLogger(__name__)
_TOKEN = re.compile(r"^[A-Za-z0-9_-]{43}$")


def requires_email_verification(user: User) -> bool:
    return get_settings().email_verification_enabled and user.email_verified_at is None


def verification_page_url() -> str:
    base = get_settings().frontend_base_url
    if base is None:
        raise ValueError("Email verification is not configured")
    return f"{str(base).rstrip('/')}/verify-email"


async def mcp_subject_allowed(session: AsyncSession, user_id: uuid.UUID) -> bool:
    if not get_settings().email_verification_enabled:
        return True
    user = await session.get(User, user_id)
    return user is not None and user.is_active and not requires_email_verification(user)


async def issue_verification_email(session: AsyncSession, user: User) -> bool:
    """Persist a hash before delivery; a failed resend never invalidates an earlier link."""
    if not user.is_active or not requires_email_verification(user):
        return False
    try:
        await enforce_verification_delivery_limit()
    except (AuthRateLimitExceeded, AuthRateLimitUnavailable):
        logger.warning("Verification delivery budget unavailable")
        return False
    now = datetime.now(UTC)
    # Bounded per-user cleanup; no polling or new scheduled database workload.
    await session.execute(
        delete(EmailVerificationToken)
        .execution_options(synchronize_session="fetch")
        .where(
            EmailVerificationToken.user_id == user.id,
            (EmailVerificationToken.expires_at <= now)
            | (EmailVerificationToken.consumed_at.is_not(None)),
        )
    )
    raw = secrets.token_urlsafe(32)
    record = EmailVerificationToken(
        id=uuid.uuid4(),
        user_id=user.id,
        email=user.email,
        token_hash=hashlib.sha256(raw.encode()).hexdigest(),
        expires_at=now + timedelta(minutes=get_settings().email_verification_expire_minutes),
    )
    session.add(record)
    await session.commit()
    try:
        await send_verification_email(
            recipient=user.email,
            url=f"{verification_page_url()}#token={raw}",
            delivery_id=str(record.id),
        )
    except EmailDeliveryError:
        # No recipient, provider body, key, or verification URL in logs.
        logger.warning("Verification email delivery failed")
        await session.execute(
            update(EmailVerificationToken)
            .execution_options(synchronize_session="fetch")
            .where(EmailVerificationToken.id == record.id)
            .values(consumed_at=func.now())
        )
        await session.commit()
        return False
    return True


async def verify_email_token(session: AsyncSession, raw: str) -> bool:
    if _TOKEN.fullmatch(raw) is None:
        return False
    return await _claim_verification(session, hashlib.sha256(raw.encode()).hexdigest()) is not None


async def _claim_verification(session: AsyncSession, digest: str) -> User | None:
    owner = await session.scalar(
        select(EmailVerificationToken.user_id).where(EmailVerificationToken.token_hash == digest)
    )
    if owner is None:
        return None
    # Lock the account before any token row. All claims for one user use this order,
    # so two different resend links cannot deadlock or verify the account twice.
    user = await session.scalar(
        select(User)
        .where(User.id == owner)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if user is None or not user.is_active or user.email_verified_at is not None:
        await session.rollback()
        return None
    claim = await session.scalar(
        update(EmailVerificationToken)
        .execution_options(synchronize_session="fetch")
        .where(
            EmailVerificationToken.token_hash == digest,
            EmailVerificationToken.user_id == user.id,
            EmailVerificationToken.email == user.email,
            EmailVerificationToken.consumed_at.is_(None),
            # Evaluate after the user lock, not at PostgreSQL transaction start.
            EmailVerificationToken.expires_at > datetime.now(UTC),
        )
        .values(consumed_at=func.now())
        .returning(EmailVerificationToken.id)
    )
    if claim is None:
        await session.rollback()
        return None
    user.email_verified_at = datetime.now(UTC)
    # A successful proof invalidates all outstanding codes and legacy links for the account.
    await session.execute(
        update(EmailVerificationToken)
        .execution_options(synchronize_session="fetch")
        .where(
            EmailVerificationToken.user_id == user.id, EmailVerificationToken.consumed_at.is_(None)
        )
        .values(consumed_at=func.now())
    )
    await session.commit()
    return user


def _code_digest(identifier: uuid.UUID, email: str, code: str) -> str:
    # A keyed, per-delivery hash protects the small code space if the DB is exposed.
    import hmac

    value = f"email-verification-code-v1:{identifier}:{email}:{code}"
    return hmac.new(
        get_settings().jwt_secret_key.encode(), value.encode(), hashlib.sha256
    ).hexdigest()


async def issue_verification_code(session: AsyncSession, user: User) -> bool:
    """Send a six-digit code automatically; keep earlier codes valid on delivery failure."""
    from ops_pilot.services.transactional_email import send_verification_code

    if not user.is_active or not requires_email_verification(user):
        return False
    try:
        await enforce_verification_delivery_limit()
    except (AuthRateLimitExceeded, AuthRateLimitUnavailable):
        logger.warning("Verification delivery budget unavailable")
        return False
    now = datetime.now(UTC)
    await session.execute(
        delete(EmailVerificationToken)
        .execution_options(synchronize_session="fetch")
        .where(
            EmailVerificationToken.user_id == user.id,
            (EmailVerificationToken.expires_at <= now)
            | EmailVerificationToken.consumed_at.is_not(None),
        )
    )
    identifier = uuid.uuid4()
    code = f"{secrets.randbelow(1_000_000):06d}"
    minutes = 10
    record = EmailVerificationToken(
        id=identifier,
        user_id=user.id,
        email=user.email,
        token_hash=_code_digest(identifier, user.email, code),
        expires_at=now + timedelta(minutes=minutes),
    )
    session.add(record)
    await session.commit()
    try:
        await send_verification_code(
            recipient=user.email, code=code, minutes=minutes, delivery_id=str(identifier)
        )
    except EmailDeliveryError:
        logger.warning("Verification code delivery failed")
        await session.execute(
            update(EmailVerificationToken)
            .execution_options(synchronize_session="fetch")
            .where(EmailVerificationToken.id == identifier)
            .values(consumed_at=func.now())
        )
        await session.commit()
        return False
    return True


async def verify_email_code(session: AsyncSession, email: str, code: str) -> User | None:
    """Call only after the peer and account attempt limits have been enforced."""
    import hmac

    if not get_settings().email_verification_enabled or re.fullmatch(r"[0-9]{6}", code) is None:
        return None
    address = email.strip().lower()
    candidates = await session.execute(
        select(EmailVerificationToken)
        .join(User, User.id == EmailVerificationToken.user_id)
        .where(
            User.email == address,
            EmailVerificationToken.email == address,
            EmailVerificationToken.consumed_at.is_(None),
            EmailVerificationToken.expires_at > datetime.now(UTC),
        )
    )
    for record in candidates.scalars():
        digest = _code_digest(record.id, address, code)
        if hmac.compare_digest(record.token_hash, digest):
            return await _claim_verification(session, digest)
    return None
