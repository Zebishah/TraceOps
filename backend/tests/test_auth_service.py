from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from ops_pilot.models.organization import Organization
from ops_pilot.models.user import User
from ops_pilot.schemas.auth import RegisterRequest
from ops_pilot.services.auth import (
    EmailAlreadyRegisteredError,
    OrganizationSlugAlreadyExistsError,
    register_user,
)


def make_result(value: object | None) -> MagicMock:
    result = MagicMock()
    result.scalar_one_or_none.return_value = value

    return result


@pytest.mark.anyio
async def test_registration_rejects_duplicate_email() -> None:
    session = AsyncMock(spec=AsyncSession)

    existing_user = MagicMock(spec=User)

    session.execute.return_value = make_result(existing_user)

    payload = RegisterRequest(
        email="zohaib@example.com",
        full_name="Zohaib Haider",
        password="StrongPassword123!",
        organization_name="Zohaib Labs",
        organization_slug="zohaib-labs",
    )

    with pytest.raises(EmailAlreadyRegisteredError):
        await register_user(
            session,
            payload,
        )

    session.rollback.assert_awaited_once()


@pytest.mark.anyio
async def test_registration_rejects_duplicate_slug() -> None:
    session = AsyncMock(spec=AsyncSession)

    existing_organization = MagicMock(spec=Organization)

    session.execute.side_effect = [
        make_result(None),
        make_result(existing_organization),
    ]

    payload = RegisterRequest(
        email="zohaib@example.com",
        full_name="Zohaib Haider",
        password="StrongPassword123!",
        organization_name="Zohaib Labs",
        organization_slug="zohaib-labs",
    )

    with pytest.raises(OrganizationSlugAlreadyExistsError):
        await register_user(
            session,
            payload,
        )

    session.rollback.assert_awaited_once()


@pytest.mark.anyio
async def test_registration_rolls_back_when_database_write_fails() -> None:
    session = AsyncMock(spec=AsyncSession)

    session.execute.side_effect = [
        make_result(None),
        make_result(None),
    ]

    session.flush.side_effect = RuntimeError("database write failed")

    payload = RegisterRequest(
        email="zohaib@example.com",
        full_name="Zohaib Haider",
        password="StrongPassword123!",
        organization_name="Zohaib Labs",
        organization_slug="zohaib-labs",
    )

    with pytest.raises(
        RuntimeError,
        match="database write failed",
    ):
        await register_user(
            session,
            payload,
        )

    session.rollback.assert_awaited_once()
    session.commit.assert_not_awaited()
