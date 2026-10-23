import uuid

from ops_pilot.inngest.functions.document_processing import (
    _should_ignore_failure,
)
from ops_pilot.models.background_job import (
    BackgroundJob,
    BackgroundJobStatus,
    BackgroundJobType,
)


def make_job(
    status: BackgroundJobStatus,
    dispatch_id: uuid.UUID,
) -> BackgroundJob:
    return BackgroundJob(
        organization_id=uuid.uuid4(),
        created_by_user_id=None,
        job_type=BackgroundJobType.DOCUMENT_PROCESSING,
        status=status,
        resource_id=uuid.uuid4(),
        idempotency_key="test-stale-failure",
        dispatch_id=dispatch_id,
    )


def test_stale_dispatch_failure_is_ignored() -> None:
    current_dispatch_id = uuid.uuid4()
    old_dispatch_id = uuid.uuid4()

    job = make_job(
        BackgroundJobStatus.PROCESSING,
        current_dispatch_id,
    )

    assert _should_ignore_failure(
        job=job,
        dispatch_id=old_dispatch_id,
    )


def test_succeeded_job_failure_is_ignored() -> None:
    dispatch_id = uuid.uuid4()

    job = make_job(
        BackgroundJobStatus.SUCCEEDED,
        dispatch_id,
    )

    assert _should_ignore_failure(
        job=job,
        dispatch_id=dispatch_id,
    )


def test_current_processing_failure_is_allowed() -> None:
    dispatch_id = uuid.uuid4()

    job = make_job(
        BackgroundJobStatus.PROCESSING,
        dispatch_id,
    )

    assert not _should_ignore_failure(
        job=job,
        dispatch_id=dispatch_id,
    )
