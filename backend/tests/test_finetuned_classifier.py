from unittest.mock import AsyncMock

import httpx
import pytest

from ops_pilot.ai import finetuned_classifier as worker
from ops_pilot.ai import incident_classifier as classifier
from ops_pilot.core.config import get_settings
from ops_pilot.schemas.incident_classification import IncidentClassification
from tests.test_security_config import make_settings


@pytest.fixture
def settings(monkeypatch):
    result = get_settings().model_copy(
        update={
            "incident_classifier_backend": "finetuned",
            "finetuned_classifier_url": "http://127.0.0.1:8001/classify",
            "finetuned_classifier_token": "x" * 32,
        }
    )
    monkeypatch.setattr(classifier, "get_settings", lambda: result)
    monkeypatch.setattr(worker, "get_settings", lambda: result)
    return result


@pytest.mark.asyncio
async def test_default_backend_never_calls_finetuned_model(monkeypatch):
    existing = AsyncMock(
        return_value=IncidentClassification(
            category="payment",
            priority="high",
            confidence=0.9,
        )
    )
    trained = AsyncMock()
    monkeypatch.setattr(classifier, "_classify_with_groq", existing)
    monkeypatch.setattr(classifier, "classify_with_finetuned_model", trained)
    assert (await classifier.classify_incident(title="t", description="d")).confidence == 0.9
    trained.assert_not_awaited()


@pytest.mark.asyncio
async def test_valid_adapter_labels_preserve_contract(monkeypatch, settings):
    original = httpx.AsyncClient

    def handler(request):
        assert request.headers["authorization"] == "Bearer " + "x" * 32
        return httpx.Response(200, json={"category": "payment", "priority": "high"})

    monkeypatch.setattr(
        worker.httpx,
        "AsyncClient",
        lambda **kw: original(
            transport=httpx.MockTransport(handler),
            **kw,
        ),
    )
    result = await classifier.classify_incident(title="Charge", description="Charged twice")
    assert result.category == "payment"
    assert result.priority == "high"
    assert result.confidence is None  # Explicitly unavailable, not a fabricated score.


@pytest.mark.asyncio
async def test_worker_failure_falls_back_to_existing_classifier(monkeypatch, settings):
    monkeypatch.setattr(
        classifier,
        "classify_with_finetuned_model",
        AsyncMock(
            side_effect=worker.FineTunedClassifierError("failed"),
        ),
    )
    existing = AsyncMock(
        return_value=IncidentClassification(
            category="system",
            priority="critical",
            confidence=0.8,
        )
    )
    monkeypatch.setattr(classifier, "_classify_with_groq", existing)
    assert (await classifier.classify_incident(title="t", description="d")).category == "system"
    existing.assert_awaited_once()


@pytest.mark.asyncio
async def test_fallback_can_be_disabled(monkeypatch, settings):
    settings.finetuned_classifier_fallback_enabled = False
    monkeypatch.setattr(
        classifier,
        "classify_with_finetuned_model",
        AsyncMock(
            side_effect=worker.FineTunedClassifierError("failed"),
        ),
    )
    existing = AsyncMock()
    monkeypatch.setattr(classifier, "_classify_with_groq", existing)
    with pytest.raises(worker.FineTunedClassifierError):
        await classifier.classify_incident(title="t", description="d")
    existing.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "payload",
    [
        {"category": "invented", "priority": "high"},
        {"category": "payment", "priority": "high", "refund": True},
        {"category": "payment", "priority": "high", "confidence": 0.99},
    ],
)
async def test_worker_outputs_are_strict(monkeypatch, settings, payload):
    original = httpx.AsyncClient
    monkeypatch.setattr(
        worker.httpx,
        "AsyncClient",
        lambda **kw: original(
            transport=httpx.MockTransport(lambda request: httpx.Response(200, json=payload)),
            **kw,
        ),
    )
    with pytest.raises(worker.FineTunedClassifierError):
        await worker.classify_with_finetuned_model(title="t", description="d")


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com/classify",
        "https://user:password@example.com/classify",
        "https://example.com/classify?key=secret",
        "file:///model",
        "https://example.com/#fragment",
    ],
)
def test_worker_url_security(url):
    with pytest.raises(ValueError):
        make_settings(
            incident_classifier_backend="finetuned",
            finetuned_classifier_url=url,
            finetuned_classifier_token="x" * 32,
        )


def test_disabled_worker_needs_no_training_configuration():
    assert make_settings().incident_classifier_backend == "groq"


def test_tts_requires_voice_feature():
    with pytest.raises(ValueError, match="VOICE_TTS_ENABLED"):
        make_settings(voice_tts_enabled=True)


@pytest.mark.asyncio
async def test_wrong_or_missing_release_header_is_rejected(monkeypatch, settings):
    settings.finetuned_classifier_release_id = "a" * 64
    original = httpx.AsyncClient
    monkeypatch.setattr(
        worker.httpx,
        "AsyncClient",
        lambda **kw: original(
            transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    200, json={"category": "payment", "priority": "high"}
                )
            ),
            **kw,
        ),
    )
    with pytest.raises(worker.FineTunedClassifierError):
        await worker.classify_with_finetuned_model(title="t", description="d")


def test_production_adapter_configuration_requires_release_identity():
    with pytest.raises(ValueError, match="approved release"):
        make_settings(
            environment="production",
            incident_classifier_backend="finetuned",
            finetuned_classifier_url="https://classifier.example/classify",
            finetuned_classifier_token="x" * 32,
        )
