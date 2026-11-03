"""Opt-in client for a separately served, evaluated classification adapter."""

import logging
import time

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
    started = time.perf_counter()
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
                if (
                    settings.finetuned_classifier_release_id
                    and response.headers.get("X-Classifier-Release")
                    != settings.finetuned_classifier_release_id
                ):
                    raise FineTunedClassifierError("Worker release does not match approved release")
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    if len(body) + len(chunk) > 4096:
                        raise FineTunedClassifierError("Classifier response exceeds limit")
                    body.extend(chunk)
        labels = ClassifierLabels.model_validate_json(body)
    except (httpx.HTTPError, ValidationError, FineTunedClassifierError) as exc:
        logging.getLogger(__name__).warning(
            "classifier_worker_prediction",
            extra={"outcome": "error", "latency_seconds": time.perf_counter() - started},
        )
        raise FineTunedClassifierError("Fine-tuned classification failed") from exc
    logging.getLogger(__name__).info(
        "classifier_worker_prediction",
        extra={
            "outcome": "valid",
            "latency_seconds": time.perf_counter() - started,
            "release_id": settings.finetuned_classifier_release_id,
        },
    )
    return IncidentClassification(
        category=labels.category, priority=labels.priority, confidence=None
    )
