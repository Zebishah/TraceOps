from unittest.mock import AsyncMock

import pytest

import ops_pilot.api.routes.health as health_module


@pytest.mark.anyio
async def test_readiness_returns_ready(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        health_module,
        "check_database",
        AsyncMock(
            return_value=(
                True,
                1.0,
            )
        ),
    )

    monkeypatch.setattr(
        health_module,
        "check_redis",
        AsyncMock(
            return_value=(
                True,
                2.0,
            )
        ),
    )

    monkeypatch.setattr(
        health_module,
        "check_qdrant",
        AsyncMock(
            return_value=(
                True,
                3.0,
            )
        ),
    )

    response = await health_module.readiness_check()

    assert response.status_code == 200


@pytest.mark.anyio
async def test_readiness_returns_503_when_dependency_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        health_module,
        "check_database",
        AsyncMock(
            return_value=(
                True,
                1.0,
            )
        ),
    )

    monkeypatch.setattr(
        health_module,
        "check_redis",
        AsyncMock(
            return_value=(
                True,
                2.0,
            )
        ),
    )

    monkeypatch.setattr(
        health_module,
        "check_qdrant",
        AsyncMock(
            return_value=(
                False,
                3.0,
            )
        ),
    )

    response = await health_module.readiness_check()

    assert response.status_code == 503
