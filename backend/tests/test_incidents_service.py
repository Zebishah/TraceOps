import asyncio
import uuid
from typing import cast
from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from ops_pilot.core.exceptions import CustomerNotFoundError
from ops_pilot.schemas.incidents import IncidentCreateRequest
from ops_pilot.services.incidents import create_incident


def test_create_incident_rejects_customer_from_another_organization() -> None:
    organization_id = uuid.uuid4()
    customer_id = uuid.uuid4()
    user_id = uuid.uuid4()

    session = AsyncMock(spec=AsyncSession)

    result = Mock()
    result.scalar_one_or_none.return_value = None
    session.execute.return_value = result

    payload = IncidentCreateRequest(
        subject_customer_id=customer_id,
        title="Customer charged twice",
        description="Why was I charged twice?",
    )

    async def run() -> None:
        with pytest.raises(CustomerNotFoundError):
            await create_incident(
                session=cast(AsyncSession, session),
                organization_id=organization_id,
                user_id=user_id,
                payload=payload,
            )

    asyncio.run(run())

    session.add.assert_not_called()
    session.commit.assert_not_awaited()
