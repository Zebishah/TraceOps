import uuid
from types import SimpleNamespace

import ops_pilot.cache.keys as redis_keys_module


def test_build_incident_cache_key(
    monkeypatch,
) -> None:
    organization_id = uuid.UUID("11111111-1111-1111-1111-111111111111")

    incident_id = uuid.UUID("22222222-2222-2222-2222-222222222222")

    monkeypatch.setattr(
        redis_keys_module,
        "get_settings",
        lambda: SimpleNamespace(
            redis_key_prefix="ops_pilot",
        ),
    )

    result = redis_keys_module.build_incident_cache_key(
        organization_id=organization_id,
        incident_id=incident_id,
    )

    assert result == (
        "ops_pilot:"
        "v1:"
        "cache:"
        "org:"
        "11111111-1111-1111-1111-111111111111:"
        "incident:"
        "22222222-2222-2222-2222-222222222222"
    )
