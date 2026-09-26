from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ops_pilot.core.exceptions import (
    EmailAlreadyRegisteredError,
    OrganizationSlugAlreadyExistsError,
    RegistrationConflictError,
)
from ops_pilot.core.security import hash_password, verify_password
from ops_pilot.models.membership import Membership, MembershipRole
from ops_pilot.models.organization import Organization
from ops_pilot.models.user import User
from ops_pilot.schemas.auth import RegisterRequest


async def get_user_by_email(
    session: AsyncSession,
    email: str,
) -> User | None:
    result = await session.execute(select(User).where(User.email == email.lower()))

    return result.scalar_one_or_none()


async def get_organization_by_slug(
    session: AsyncSession,
    slug: str,
) -> Organization | None:
    result = await session.execute(select(Organization).where(Organization.slug == slug.lower()))

    return result.scalar_one_or_none()


async def register_user(
    session: AsyncSession,
    payload: RegisterRequest,
) -> User:
    try:
        existing_user = await get_user_by_email(
            session,
            payload.email,
        )

        if existing_user is not None:
            raise EmailAlreadyRegisteredError

        existing_organization = await get_organization_by_slug(
            session,
            payload.organization_slug,
        )

        if existing_organization is not None:
            raise OrganizationSlugAlreadyExistsError

        organization = Organization(
            name=payload.organization_name,
            slug=payload.organization_slug.lower(),
        )

        user = User(
            email=payload.email.lower(),
            full_name=payload.full_name,
            password_hash=hash_password(payload.password),
        )

        session.add_all(
            [
                organization,
                user,
            ]
        )

        await session.flush()

        membership = Membership(
            organization_id=organization.id,
            user_id=user.id,
            role=MembershipRole.OWNER,
        )

        session.add(membership)

        await session.commit()

        return user

    except (
        EmailAlreadyRegisteredError,
        OrganizationSlugAlreadyExistsError,
    ):
        await session.rollback()
        raise

    except IntegrityError as exc:
        await session.rollback()

        raise RegistrationConflictError from exc

    except Exception:
        await session.rollback()
        raise


async def authenticate_user(
    session: AsyncSession,
    email: str,
    password: str,
) -> User | None:
    user = await get_user_by_email(
        session,
        email,
    )

    if user is None:
        return None

    if not verify_password(
        password,
        user.password_hash,
    ):
        return None

    if not user.is_active:
        return None

    return user
