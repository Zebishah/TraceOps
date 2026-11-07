"""Private supervised model worker with signed production releases and hard deadlines."""

import asyncio
import base64
import hmac
import logging
import time
from collections import Counter
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated, Literal

from fastapi import FastAPI, Header, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from finetuning.artifacts import verify_artifact
from finetuning.http_limits import WorkerBodyLimitMiddleware
from finetuning.process_worker import InvalidPrediction, ProcessModelWorker
from finetuning.release import verify_release
from ops_pilot.ai.finetuned_classifier import ClassifierLabels


class WorkerSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="CLASSIFIER_", extra="ignore", hide_input_in_errors=True
    )
    adapter_path: Path
    serving_token: str = Field(min_length=32, max_length=256)
    environment: Literal["production", "development"] = "production"
    release_manifest: Path | None = None
    release_public_key: str | None = None
    device: Literal["cpu", "cuda"] = "cpu"
    qlora: bool | None = None
    generation_timeout_seconds: float = Field(default=8, gt=0, le=60)
    startup_timeout_seconds: float = Field(default=120, gt=0, le=600)
    cpu_threads: int = Field(default=2, ge=1, le=64)

    @model_validator(mode="after")
    def approved_production(self):
        if self.environment == "production" and (
            self.release_manifest is None or not self.release_public_key
        ):
            raise ValueError("Production worker requires a signed release and trusted public key")
        if (self.release_manifest is None) != (self.release_public_key is None):
            raise ValueError("Release manifest and public key must be configured together")
        return self


class ClassificationInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    title: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=8192)


class WorkerMetrics:
    outcomes = ("valid", "invalid", "timeout", "busy", "unauthorized", "error")
    bounds = (0.1, 0.25, 0.5, 1, 2, 5, 10, 30)

    def __init__(self):
        self.results = Counter()
        self.distribution = Counter()
        self.duration_count = 0
        self.duration_sum = 0.0
        self.buckets = Counter()

    def record(self, outcome, duration=0.0, labels=None):
        self.results[outcome] += 1
        if outcome != "unauthorized":
            self.duration_count += 1
            self.duration_sum += duration
            for bound in self.bounds:
                if duration <= bound:
                    self.buckets[bound] += 1
        if labels is not None:
            self.distribution[(str(labels.category), str(labels.priority))] += 1

    def render(self, ready, peak_rss_mib=0):
        lines = [
            "# TYPE opspilot_classifier_ready gauge",
            f"opspilot_classifier_ready {int(ready)}",
            "# TYPE opspilot_classifier_peak_rss_mib gauge",
            f"opspilot_classifier_peak_rss_mib {peak_rss_mib}",
            "# TYPE opspilot_classifier_requests_total counter",
        ]
        for outcome in self.outcomes:
            lines.append(
                f'opspilot_classifier_requests_total{{outcome="{outcome}"}} {self.results[outcome]}'
            )
        lines.append("# TYPE opspilot_classifier_prediction_total counter")
        for (category, priority), count in sorted(self.distribution.items()):
            lines.append(
                f'opspilot_classifier_prediction_total{{category="{category}",'
                f'priority="{priority}"}} {count}'
            )
        lines.append("# TYPE opspilot_classifier_duration_seconds histogram")
        for bound in self.bounds:
            lines.append(
                f'opspilot_classifier_duration_seconds_bucket{{le="{bound}"}} {self.buckets[bound]}'
            )
        lines.extend(
            [
                f'opspilot_classifier_duration_seconds_bucket{{le="+Inf"}} {self.duration_count}',
                f"opspilot_classifier_duration_seconds_count {self.duration_count}",
                f"opspilot_classifier_duration_seconds_sum {self.duration_sum}",
            ]
        )
        return "\n".join(lines) + "\n"


def create_model_worker(settings):
    return ProcessModelWorker(
        settings.adapter_path,
        device=settings.device,
        qlora=settings.qlora,
        startup_timeout=settings.startup_timeout_seconds,
        prediction_timeout=settings.generation_timeout_seconds,
        cpu_threads=settings.cpu_threads,
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = WorkerSettings()
    artifact = verify_artifact(settings.adapter_path)
    release_id = "development"
    if settings.release_manifest is not None:
        public_key = base64.b64decode(settings.release_public_key, validate=True)
        release_id = verify_release(settings.adapter_path, settings.release_manifest, public_key)
    app.state.settings = settings
    app.state.artifact = artifact
    app.state.release_id = release_id
    app.state.metrics = WorkerMetrics()
    app.state.slot = asyncio.Semaphore(1)
    app.state.worker = create_model_worker(settings)
    await app.state.worker.start()
    try:
        yield
    finally:
        await app.state.worker.close()


def create_app():
    app = FastAPI(
        title="IncidentIQ classifier worker",
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.add_middleware(WorkerBodyLimitMiddleware)

    def authorize(authorization):
        expected = f"Bearer {app.state.settings.serving_token}"
        if not hmac.compare_digest(authorization.encode(), expected.encode()):
            app.state.metrics.record("unauthorized")
            raise HTTPException(status_code=401, detail="Invalid worker credentials")

    @app.get("/health/live")
    async def live():
        return {"status": "alive"}

    @app.get("/health/ready")
    async def ready(response: Response):
        available = app.state.worker.ready
        if not available:
            app.state.worker.ensure_recovery()
        response.status_code = 200 if available else 503
        return {
            "ready": available,
            "release_id": app.state.release_id,
            "artifact_sha256": app.state.artifact.fingerprint(),
        }

    @app.get("/metrics")
    async def metrics(authorization: Annotated[str, Header()] = ""):
        authorize(authorization)
        return Response(
            content=app.state.metrics.render(
                app.state.worker.ready, getattr(app.state.worker, "peak_rss_mib", 0)
            ),
            media_type="text/plain; version=0.0.4",
        )

    @app.post("/classify", response_model=ClassifierLabels)
    async def classify(
        payload: ClassificationInput,
        response: Response,
        authorization: Annotated[str, Header()] = "",
    ):
        authorize(authorization)
        started = time.perf_counter()
        if not app.state.worker.ready:
            app.state.worker.ensure_recovery()
            app.state.metrics.record("error")
            raise HTTPException(status_code=503, detail="Classifier is not ready")
        try:
            await asyncio.wait_for(app.state.slot.acquire(), timeout=0.1)
        except TimeoutError as exc:
            app.state.metrics.record("busy", time.perf_counter() - started)
            raise HTTPException(status_code=503, detail="Classifier busy") from exc
        outcome = "error"
        labels = None
        try:
            labels = await app.state.worker.predict(
                title=payload.title, description=payload.description
            )
            outcome = "valid"
            response.headers["X-Classifier-Release"] = app.state.release_id
            response.headers["Cache-Control"] = "no-store"
            return labels
        except InvalidPrediction as exc:
            outcome = "invalid"
            raise HTTPException(
                status_code=422, detail="Classifier returned invalid labels"
            ) from exc
        except TimeoutError as exc:
            outcome = "timeout"
            raise HTTPException(status_code=504, detail="Classifier computation timed out") from exc
        except (RuntimeError, OSError, ValueError) as exc:
            raise HTTPException(status_code=503, detail="Classifier unavailable") from exc
        finally:
            elapsed = time.perf_counter() - started
            app.state.metrics.record(outcome, elapsed, labels)
            logging.getLogger(__name__).info(
                "classifier_worker_request",
                extra={
                    "outcome": outcome,
                    "duration_ms": round(elapsed * 1000),
                    "release_id": app.state.release_id,
                },
            )
            app.state.slot.release()

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("finetuning.serve_classifier:app", host="127.0.0.1", port=8001, workers=1)
