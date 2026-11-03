"""The model worker can be tested without installing training libraries."""

from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from finetuning import serve_classifier as worker
from ops_pilot.ai.finetuned_classifier import ClassifierLabels


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("CLASSIFIER_SERVING_TOKEN", "x" * 32)
    monkeypatch.setenv("CLASSIFIER_ADAPTER_PATH", "/unused/test-adapter")
    monkeypatch.setattr(worker, "load_runtime", lambda *a, **kw: (object(), object()))
    with TestClient(worker.app) as client:
        yield client


def test_private_worker_requires_token(client, monkeypatch):
    call = Mock()
    monkeypatch.setattr(worker, "predict_labels", call)
    assert client.post("/classify", json={"title": "t", "description": "d"}).status_code == 401
    call.assert_not_called()


def test_worker_returns_validated_labels(client, monkeypatch):
    monkeypatch.setattr(
        worker,
        "predict_labels",
        lambda *a, **kw: ClassifierLabels(
            category="payment",
            priority="high",
        ),
    )
    response = client.post(
        "/classify",
        json={"title": "t", "description": "d"},
        headers={"Authorization": "Bearer " + "x" * 32},
    )
    assert response.status_code == 200
    assert response.json() == {"category": "payment", "priority": "high"}


def test_worker_rejects_invalid_output_without_leaking_data(client, monkeypatch):
    def invalid(*args, **kwargs):
        raise ValueError("sensitive model output")

    monkeypatch.setattr(worker, "predict_labels", invalid)
    response = client.post(
        "/classify",
        json={"title": "t", "description": "d"},
        headers={"Authorization": "Bearer " + "x" * 32},
    )
    assert response.status_code == 422
    assert "sensitive" not in response.text
