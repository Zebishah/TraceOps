"""Account recovery with one-time proof, generic requests, and versioned sessions."""

import hashlib
import logging
import re
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ops_pilot.core.config import get_settings
from ops_pilot.core.security import hash_password
from ops_pilot.models.password_reset_token import PasswordResetToken
from ops_pilot.models.user import User
from ops_pilot.services.transactional_email import EmailDeliveryError, send_password_reset_email

logger = logging.getLogger(__name__)
_TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_-]{43}$")


async def request_password_reset(session: AsyncSession, email: str) -> None:
    settings = get_settings()
    if not settings.email_verification_enabled or not settings.frontend_base_url:
        return
    address = email.strip().lower()
    result = await session.execute(select(User).where(User.email == address).with_for_update())
    user = result.scalar_one_or_none()
    if user is None or not user.is_active or user.email_verified_at is None:
        await session.rollback()
        return
    recent = await session.execute(
        select(PasswordResetToken.id)
        .where(
            PasswordResetToken.user_id == user.id,
            PasswordResetToken.created_at > datetime.now(UTC) - timedelta(seconds=60),
        )
        .limit(1)
    )
    if recent.first():
        await session.rollback()
        return
    token = secrets.token_urlsafe(32)
    record = PasswordResetToken(
        id=uuid.uuid4(),
        user_id=user.id,
        token_hash=hashlib.sha256(token.encode()).hexdigest(),
        expires_at=datetime.now(UTC) + timedelta(minutes=30),
    )
    session.add(record)
    await session.commit()
    url = f"{str(settings.frontend_base_url).rstrip('/')}/reset-password#token={token}"
    try:
        await send_password_reset_email(recipient=user.email, url=url, delivery_id=str(record.id))
    except EmailDeliveryError:
        # Never reveal account state or provider failures to the requester.
        logger.warning("Password reset email delivery failed")
        await session.execute(
            update(PasswordResetToken)
            .where(PasswordResetToken.id == record.id)
            .values(consumed_at=func.now())
        )
        await session.commit()


async def confirm_password_reset(session: AsyncSession, token: str, password: str) -> bool:
    if _TOKEN_PATTERN.fullmatch(token) is None:
        return False
    digest = hashlib.sha256(token.encode()).hexdigest()
    candidate = await session.execute(
        select(PasswordResetToken.user_id).where(PasswordResetToken.token_hash == digest)
    )
    user_id = candidate.scalar_one_or_none()
    if user_id is None:
        return False
    result = await session.execute(select(User).where(User.id == user_id).with_for_update())
    user = result.scalar_one_or_none()
    if user is None or not user.is_active or user.email_verified_at is None:
        await session.rollback()
        return False
    claimed = await session.execute(
        update(PasswordResetToken)
        .where(
            PasswordResetToken.token_hash == digest,
            PasswordResetToken.user_id == user.id,
            PasswordResetToken.consumed_at.is_(None),
            PasswordResetToken.expires_at > datetime.now(UTC),
        )
        .values(consumed_at=func.now())
        .returning(PasswordResetToken.id)
    )
    if claimed.scalar_one_or_none() is None:
        await session.rollback()
        return False
    user.password_hash = hash_password(password)
    user.auth_version += 1
    await session.execute(
        update(PasswordResetToken)
        .where(
            PasswordResetToken.user_id == user.id,
            PasswordResetToken.consumed_at.is_(None),
        )
        .values(consumed_at=func.now())
    )
    await session.commit()
    return True
