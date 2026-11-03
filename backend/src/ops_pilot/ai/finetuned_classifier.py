"""Opt-in client for a separately served, evaluated classification adapter."""

import httpx
from pydantic import BaseModel, ConfigDict, ValidationError

from ops_pilot.core.config import get_settings
from ops_pilot.models.incident import IncidentPriority
from ops_pilot.schemas.incident_classification import IncidentCategory, IncidentClassification


class ClassifierLabels(BaseModel):
    model_config = ConfigDict(extra="forbid")
    category: IncidentCategory
    priority: IncidentPriority


class FineTunedClassifierError(RuntimeError):
    """Provider failed or produced an invalid classification."""


async def classify_with_finetuned_model(*, title: str, description: str) -> IncidentClassification:
    settings = get_settings()
    if not settings.finetuned_classifier_url or not settings.finetuned_classifier_token:
        raise FineTunedClassifierError("Fine-tuned classification is not configured")
    try:
        async with httpx.AsyncClient(
            timeout=settings.finetuned_classifier_timeout_seconds, follow_redirects=False
        ) as client:
            async with client.stream(
                "POST",
                settings.finetuned_classifier_url,
                headers={"Authorization": f"Bearer {settings.finetuned_classifier_token}"},
                json={"title": title, "description": description},
            ) as response:
                response.raise_for_status()
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    if len(body) + len(chunk) > 4096:
                        raise FineTunedClassifierError("Classifier response exceeds limit")
                    body.extend(chunk)
        labels = ClassifierLabels.model_validate_json(body)
    except (httpx.HTTPError, ValidationError) as exc:
        raise FineTunedClassifierError("Fine-tuned classification failed") from exc
    # Compatibility with the existing API. Zero means no calibrated confidence
    # is available; do not manufacture a probability from the model's prose.
    return IncidentClassification(
        category=labels.category, priority=labels.priority, confidence=0.0
    )
