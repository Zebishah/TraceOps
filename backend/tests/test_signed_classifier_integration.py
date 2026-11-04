"""Contract integration with artificial signed evidence and a fake model, not quality evidence."""

import base64
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from finetuning import serve_classifier
from finetuning.artifacts import atomic_json
from finetuning.release import approve_release
from ops_pilot.ai import finetuned_classifier, incident_classifier
from ops_pilot.ai.finetuned_classifier import ClassifierLabels, FineTunedClassifierError
from ops_pilot.core.config import get_settings
from tests.finetuning_helpers import fake_artifact, report, review, small_policy


@pytest.mark.asyncio
@pytest.mark.parametrize("wrong_expected_release", [False, True])
async def test_signed_worker_to_backend_contract(monkeypatch, tmp_path, wrong_expected_release):
    ed25519 = pytest.importorskip("cryptography.hazmat.primitives.asymmetric.ed25519")
    adapter = tmp_path / "adapter"
    artifact = fake_artifact(adapter)
    evidence = []
    for name, value in (
        ("adapter", report(artifact_sha256=artifact.fingerprint())),
        ("groq", report("groq")),
        ("review", review()),
    ):
        path = tmp_path / (name + ".json")
        atomic_json(path, value.model_dump(mode="json"))
        evidence.append(path)
    key = ed25519.Ed25519PrivateKey.generate()
    release_path = tmp_path / "release.json"
    release = approve_release(
        adapter_path=adapter,
        adapter_report=evidence[0],
        baseline_report=evidence[1],
        review_path=evidence[2],
        private_key=key.private_bytes_raw(),
        output=release_path,
        policy=small_policy(),
    )
    monkeypatch.setenv("CLASSIFIER_ENVIRONMENT", "production")
    monkeypatch.setenv("CLASSIFIER_ADAPTER_PATH", str(adapter))
    monkeypatch.setenv("CLASSIFIER_SERVING_TOKEN", "x" * 32)
    monkeypatch.setenv("CLASSIFIER_RELEASE_MANIFEST", str(release_path))
    monkeypatch.setenv(
        "CLASSIFIER_RELEASE_PUBLIC_KEY",
        base64.b64encode(key.public_key().public_bytes_raw()).decode(),
    )
    manager = SimpleNamespace(
        start=AsyncMock(),
        close=AsyncMock(),
        ready=True,
        peak_rss_mib=1,
        predict=AsyncMock(return_value=ClassifierLabels(category="payment", priority="high")),
    )
    monkeypatch.setattr(serve_classifier, "create_model_worker", lambda settings: manager)
    app = serve_classifier.create_app()
    settings = get_settings().model_copy(
        update={
            "incident_classifier_backend": "finetuned",
            "finetuned_classifier_url": "http://127.0.0.1:8001/classify",
            "finetuned_classifier_token": "x" * 32,
            "finetuned_classifier_release_id": "f" * 64 if wrong_expected_release else release,
            "finetuned_classifier_fallback_enabled": False,
        }
    )
    monkeypatch.setattr(finetuned_classifier, "get_settings", lambda: settings)
    monkeypatch.setattr(incident_classifier, "get_settings", lambda: settings)
    groq = AsyncMock(side_effect=AssertionError("Groq must not hide integration failures"))
    monkeypatch.setattr(incident_classifier, "_classify_with_groq", groq)
    original = httpx.AsyncClient
    monkeypatch.setattr(
        finetuned_classifier.httpx,
        "AsyncClient",
        lambda **kwargs: original(transport=httpx.ASGITransport(app=app), **kwargs),
    )
    async with serve_classifier.lifespan(app):
        if wrong_expected_release:
            with pytest.raises(FineTunedClassifierError):
                await incident_classifier.classify_incident(
                    title="Charge", description="Two charges"
                )
        else:
            result = await incident_classifier.classify_incident(
                title="Charge", description="Two charges"
            )
            assert result.category == "payment" and result.priority == "high"
            assert result.confidence is None
        groq.assert_not_awaited()
        manager.predict.assert_awaited_once()
    manager.start.assert_awaited_once()
    manager.close.assert_awaited_once()
