import uuid

import pytest

from ops_pilot.services.incident_background import (
    investigation_thread_id,
    validate_checkpoint_identity,
)


def test_investigation_thread_is_stable() -> None:
    job_id = uuid.uuid4()

    assert investigation_thread_id(job_id) == (f"incident-analysis:{job_id}")


def test_checkpoint_accepts_matching_identity() -> None:
    organization_id = uuid.uuid4()
    incident_id = uuid.uuid4()

    validate_checkpoint_identity(
        values={
            "organization_id": str(organization_id),
            "incident_id": str(incident_id),
        },
        organization_id=organization_id,
        incident_id=incident_id,
    )


@pytest.mark.parametrize("field", ["organization_id", "incident_id"])
def test_checkpoint_rejects_another_resource(field: str) -> None:
    organization_id = uuid.uuid4()
    incident_id = uuid.uuid4()

    values: dict[str, object] = {
        "organization_id": organization_id,
        "incident_id": incident_id,
    }
    values[field] = uuid.uuid4()

    with pytest.raises(RuntimeError, match="mismatch"):
        validate_checkpoint_identity(
            values=values,
            organization_id=organization_id,
            incident_id=incident_id,
        )


@pytest.mark.parametrize("field", ["organization_id", "incident_id"])
def test_checkpoint_rejects_missing_identity(field: str) -> None:
    organization_id = uuid.uuid4()
    incident_id = uuid.uuid4()

    values: dict[str, object] = {
        "organization_id": organization_id,
        "incident_id": incident_id,
    }
    del values[field]

    with pytest.raises(RuntimeError, match="invalid"):
        validate_checkpoint_identity(
            values=values,
            organization_id=organization_id,
            incident_id=incident_id,
        )
