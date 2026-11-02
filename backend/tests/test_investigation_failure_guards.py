import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock

import inngest
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

import ops_pilot.inngest.functions.incident_analysis as worker
from ops_pilot.models.background_job import (
    BackgroundJobStatus,
    BackgroundJobType,
)
from ops_pilot.schemas.background_jobs import BackgroundJobEventData


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "case",
    [
        "stale_dispatch",
        "wrong_resource",
        "wrong_type",
        "succeeded",
        "already_failed",
    ],
)
async def test_failure_callback_ignores_ineligible_job(
    monkeypatch: pytest.MonkeyPatch,
    case: str,
) -> None:
    data = BackgroundJobEventData(
        organization_id=uuid.uuid4(),
        resource_id=uuid.uuid4(),
        job_id=uuid.uuid4(),
        dispatch_id=uuid.uuid4(),
    )

    job = SimpleNamespace(
        job_type=BackgroundJobType.INCIDENT_ANALYSIS,
        resource_id=data.resource_id,
        dispatch_id=data.dispatch_id,
        status=BackgroundJobStatus.PROCESSING,
        progress_percent=10,
    )

    if case == "stale_dispatch":
        job.dispatch_id = uuid.uuid4()
    elif case == "wrong_resource":
        job.resource_id = uuid.uuid4()
    elif case == "wrong_type":
        job.job_type = BackgroundJobType.MEMORY_INDEXING
    elif case == "succeeded":
        job.status = BackgroundJobStatus.SUCCEEDED
    else:
        job.status = BackgroundJobStatus.FAILED

    session = cast(AsyncSession, AsyncMock())

    @asynccontextmanager
    async def sessions() -> AsyncIterator[AsyncSession]:
        yield session

    async def run_step(
        name: str,
        callback: Callable[[], Awaitable[dict[str, bool]]],
    ) -> dict[str, bool]:
        assert name == "mark-investigation-failed"
        return await callback()

    ctx = cast(
        inngest.Context,
        SimpleNamespace(
            event=SimpleNamespace(
                data={
                    "event": {
                        "data": data.model_dump(mode="json"),
                    }
                }
            ),
            step=SimpleNamespace(run=run_step),
        ),
    )

    update = AsyncMock()
    lookup = AsyncMock(return_value=job)

    monkeypatch.setattr(worker, "async_session_factory", sessions)
    monkeypatch.setattr(worker, "get_background_job", lookup)
    monkeypatch.setattr(worker, "update_job_for_dispatch", update)

    await worker.incident_analysis_on_failure(ctx)

    lookup.assert_awaited_once_with(
        session=session,
        organization_id=data.organization_id,
        job_id=data.job_id,
    )
    update.assert_not_awaited()
