from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

import ops_pilot.api.routes.health as health_module
from ops_pilot.main import app

client = TestClient(app)


def test_health_check_returns_ok() -> None:
    response = client.get("/api/v1/health")

    assert response.status_code == 200

    assert response.json() == {
        "status": "ok",
    }


def test_readiness_check_returns_ready(
    monkeypatch,
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

    response = client.get("/api/v1/health/ready")

    assert response.status_code == 200

    payload = response.json()

    assert payload["status"] == "ready"

    assert payload["dependencies"]["database"]["status"] == "connected"

    assert payload["dependencies"]["redis"]["status"] == "connected"

    assert payload["dependencies"]["qdrant"]["status"] == "connected"


def test_readiness_check_returns_503_when_database_unavailable(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        health_module,
        "check_database",
        AsyncMock(
            return_value=(
                False,
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

    response = client.get("/api/v1/health/ready")

    assert response.status_code == 503

    payload = response.json()

    assert payload["status"] == "not_ready"

    assert payload["dependencies"]["database"]["status"] == "unavailable"

    assert payload["dependencies"]["redis"]["status"] == "connected"

    assert payload["dependencies"]["qdrant"]["status"] == "connected"


def test_readiness_check_returns_503_when_redis_unavailable(
    monkeypatch,
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
                False,
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

    response = client.get("/api/v1/health/ready")

    assert response.status_code == 503

    payload = response.json()

    assert payload["status"] == "not_ready"

    assert payload["dependencies"]["database"]["status"] == "connected"

    assert payload["dependencies"]["redis"]["status"] == "unavailable"

    assert payload["dependencies"]["qdrant"]["status"] == "connected"


def test_readiness_check_returns_503_when_qdrant_unavailable(
    monkeypatch,
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

    response = client.get("/api/v1/health/ready")

    assert response.status_code == 503

    payload = response.json()

    assert payload["status"] == "not_ready"

    assert payload["dependencies"]["qdrant"]["status"] == "unavailable"
