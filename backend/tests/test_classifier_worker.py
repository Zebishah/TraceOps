"""HTTP worker tests use a fake model manager; process isolation has separate tests."""

from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from finetuning import serve_classifier as worker
from finetuning.http_limits import WorkerBodyLimitMiddleware
from finetuning.process_worker import InvalidPrediction
from ops_pilot.ai.finetuned_classifier import ClassifierLabels
from tests.finetuning_helpers import fake_artifact


@pytest.fixture
def client(monkeypatch, tmp_path):
    adapter = tmp_path / "adapter"
    fake_artifact(adapter)
    monkeypatch.setenv("CLASSIFIER_SERVING_TOKEN", "x" * 32)
    monkeypatch.setenv("CLASSIFIER_ADAPTER_PATH", str(adapter))
    monkeypatch.setenv("CLASSIFIER_ENVIRONMENT", "development")
    monkeypatch.delenv("CLASSIFIER_RELEASE_MANIFEST", raising=False)
    monkeypatch.delenv("CLASSIFIER_RELEASE_PUBLIC_KEY", raising=False)

    class FakeWorker:
        ready = True
        start = AsyncMock()
        close = AsyncMock()

        def ensure_recovery(self):
            pass

        predict = AsyncMock(return_value=ClassifierLabels(category="payment", priority="high"))

    fake = FakeWorker()
    monkeypatch.setattr(worker, "create_model_worker", lambda settings: fake)
    with TestClient(worker.create_app()) as client:
        client.model_worker = fake
        yield client


def token():
    return {"Authorization": "Bearer " + "x" * 32}


def test_private_worker_requires_token(client):
    assert client.post("/classify", json={"title": "t", "description": "d"}).status_code == 401
    client.model_worker.predict.assert_not_awaited()


def test_worker_returns_validated_labels_and_release_identity(client):
    response = client.post("/classify", json={"title": "t", "description": "d"}, headers=token())
    assert response.status_code == 200
    assert response.json() == {"category": "payment", "priority": "high"}
    assert response.headers["X-Classifier-Release"] == "development"
    assert response.headers["Cache-Control"] == "no-store"


def test_worker_rejects_invalid_output_without_leaking_data(client):
    client.model_worker.predict.side_effect = InvalidPrediction("sensitive model output")
    response = client.post("/classify", json={"title": "t", "description": "d"}, headers=token())
    assert response.status_code == 422
    assert "sensitive" not in response.text


def test_deadline_returns_504_and_is_counted(client):
    client.model_worker.predict.side_effect = TimeoutError("private diagnostic")
    response = client.post("/classify", json={"title": "t", "description": "d"}, headers=token())
    assert response.status_code == 504
    metrics = client.get("/metrics", headers=token())
    assert 'outcome="timeout"} 1' in metrics.text
    assert "private diagnostic" not in response.text


def test_health_readiness_and_authenticated_metrics(client):
    assert client.get("/health/live").status_code == 200
    assert client.get("/health/ready").json()["ready"] is True
    client.model_worker.ready = False
    assert client.get("/health/ready").status_code == 503
    assert client.get("/metrics").status_code == 401
    assert "opspilot_classifier_ready 0" in client.get("/metrics", headers=token()).text


def test_body_rejected_before_json_parsing(client):
    response = client.post("/classify", content=b"x" * (64 * 1024 + 1), headers=token())
    assert response.status_code == 413
    client.model_worker.predict.assert_not_awaited()


def test_production_worker_requires_signed_release(monkeypatch):
    monkeypatch.setenv("CLASSIFIER_ENVIRONMENT", "production")
    monkeypatch.setenv("CLASSIFIER_ADAPTER_PATH", "/unused")
    monkeypatch.setenv("CLASSIFIER_SERVING_TOKEN", "x" * 32)
    monkeypatch.delenv("CLASSIFIER_RELEASE_MANIFEST", raising=False)
    monkeypatch.delenv("CLASSIFIER_RELEASE_PUBLIC_KEY", raising=False)
    with pytest.raises(ValueError, match="signed release"):
        worker.WorkerSettings()


@pytest.mark.asyncio
async def test_chunked_body_actual_size_is_bounded():
    called = False

    async def app(scope, receive, send):
        nonlocal called
        called = True

    messages = iter(
        [
            {"type": "http.request", "body": b"123", "more_body": True},
            {"type": "http.request", "body": b"456", "more_body": False},
        ]
    )

    async def receive():
        return next(messages)

    responses = []

    async def send(message):
        responses.append(message)

    await WorkerBodyLimitMiddleware(app, max_bytes=5)(
        {"type": "http", "method": "POST", "headers": []}, receive, send
    )
    assert not called and responses[0]["status"] == 413
