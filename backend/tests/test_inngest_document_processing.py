import asyncio
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import cast
from unittest.mock import AsyncMock

from sqlalchemy.ext.asyncio import AsyncSession

import ops_pilot.inngest.functions.document_processing as module
from ops_pilot.models.background_job import (
    BackgroundJob,
    BackgroundJobStatus,
    BackgroundJobType,
)


def make_session() -> tuple[
    AsyncSession,
    AsyncMock,
]:
    session_mock = AsyncMock(
        spec=AsyncSession,
    )

    return (
        cast(
            AsyncSession,
            session_mock,
        ),
        session_mock,
    )


def make_job(
    *,
    organization_id: uuid.UUID,
    job_id: uuid.UUID,
    document_id: uuid.UUID,
) -> BackgroundJob:
    return BackgroundJob(
        id=job_id,
        organization_id=organization_id,
        created_by_user_id=None,
        job_type=(BackgroundJobType.DOCUMENT_PROCESSING),
        status=BackgroundJobStatus.QUEUED,
        resource_id=document_id,
        idempotency_key=(f"document-processing:{document_id}"),
        progress_percent=0,
    )


def test_mark_job_processing(
    monkeypatch,
) -> None:
    organization_id = uuid.uuid4()
    job_id = uuid.uuid4()
    document_id = uuid.uuid4()

    job = make_job(
        organization_id=organization_id,
        job_id=job_id,
        document_id=document_id,
    )

    session, _ = make_session()

    @asynccontextmanager
    async def fake_session_factory() -> AsyncIterator[AsyncSession]:
        yield session

    async def fake_get_background_job(
        **kwargs: object,
    ) -> BackgroundJob:
        return job

    mark_processing = AsyncMock()

    monkeypatch.setattr(
        module,
        "async_session_factory",
        fake_session_factory,
    )

    monkeypatch.setattr(
        module,
        "get_background_job",
        fake_get_background_job,
    )

    monkeypatch.setattr(
        module,
        "mark_background_job_processing",
        mark_processing,
    )

    result = asyncio.run(
        module._mark_job_processing(
            organization_id=organization_id,
            job_id=job_id,
            document_id=document_id,
        )
    )

    assert result == {
        "already_succeeded": False,
        "progress_percent": 10,
    }

    mark_processing.assert_awaited_once_with(
        session=session,
        job=job,
        progress_percent=10,
    )


def test_mark_job_processing_rejects_wrong_resource(
    monkeypatch,
) -> None:
    organization_id = uuid.uuid4()
    job_id = uuid.uuid4()

    actual_document_id = uuid.uuid4()
    requested_document_id = uuid.uuid4()

    job = make_job(
        organization_id=organization_id,
        job_id=job_id,
        document_id=actual_document_id,
    )

    session, _ = make_session()

    @asynccontextmanager
    async def fake_session_factory() -> AsyncIterator[AsyncSession]:
        yield session

    async def fake_get_background_job(
        **kwargs: object,
    ) -> BackgroundJob:
        return job

    monkeypatch.setattr(
        module,
        "async_session_factory",
        fake_session_factory,
    )

    monkeypatch.setattr(
        module,
        "get_background_job",
        fake_get_background_job,
    )

    async def run() -> None:
        try:
            await module._mark_job_processing(
                organization_id=organization_id,
                job_id=job_id,
                document_id=requested_document_id,
            )
        except RuntimeError as exc:
            assert str(exc) == ("Background job resource mismatch")
        else:
            raise AssertionError("Expected RuntimeError")

    asyncio.run(run())


def test_mark_job_succeeded(
    monkeypatch,
) -> None:
    organization_id = uuid.uuid4()
    job_id = uuid.uuid4()
    document_id = uuid.uuid4()

    job = make_job(
        organization_id=organization_id,
        job_id=job_id,
        document_id=document_id,
    )

    session, _ = make_session()

    @asynccontextmanager
    async def fake_session_factory() -> AsyncIterator[AsyncSession]:
        yield session

    async def fake_get_background_job(
        **kwargs: object,
    ) -> BackgroundJob:
        return job

    mark_succeeded = AsyncMock()

    monkeypatch.setattr(
        module,
        "async_session_factory",
        fake_session_factory,
    )

    monkeypatch.setattr(
        module,
        "get_background_job",
        fake_get_background_job,
    )

    monkeypatch.setattr(
        module,
        "mark_background_job_succeeded",
        mark_succeeded,
    )

    result = asyncio.run(
        module._mark_job_succeeded(
            organization_id=organization_id,
            job_id=job_id,
        )
    )

    assert result["status"] == "succeeded"

    mark_succeeded.assert_awaited_once_with(
        session=session,
        job=job,
    )


def test_extract_failure_event_data() -> None:
    job_id = uuid.uuid4()
    organization_id = uuid.uuid4()
    document_id = uuid.uuid4()

    result = module._extract_failure_event_data(
        {
            "event": {
                "data": {
                    "job_id": str(job_id),
                    "organization_id": str(organization_id),
                    "resource_id": str(document_id),
                }
            }
        }
    )

    assert result is not None
    assert result.job_id == job_id
    assert result.organization_id == organization_id
    assert result.resource_id == document_id


def test_extract_failure_message() -> None:
    result = module._extract_failure_message(
        {
            "error": {
                "message": "Qdrant unavailable",
            }
        }
    )

    assert result == "Qdrant unavailable"
