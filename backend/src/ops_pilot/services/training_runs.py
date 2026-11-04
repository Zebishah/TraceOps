"""Database-backed admission, leases and fencing for the separate training worker."""

import hashlib
import json
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from fastapi import HTTPException
from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import defer

from ops_pilot.core.config import get_settings
from ops_pilot.finetuning.dataset import load_examples, split_examples
from ops_pilot.models.training_run import TrainingControl, TrainingRun
from ops_pilot.schemas.training import TrainingConfig, TrainingProgress, WorkerFinish

MODEL_ID = "Qwen/Qwen2.5-0.5B-Instruct"
MODEL_REVISION = "7ae557604adf67be50417f59c2c2f167def9a775"
ACTIVE = ("queued", "running", "cancel_requested")
LEASE_SECONDS = 90
MAX_ARTIFACT_BYTES = 64 * 1024 * 1024


def enabled() -> None:
    if not get_settings().training_enabled:
        raise HTTPException(503, "Training control is disabled on this backend")


async def lock_control(session: AsyncSession) -> TrainingControl:
    control = await session.scalar(
        select(TrainingControl)
        .where(TrainingControl.id == 1)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if control is None:
        raise HTTPException(503, "Apply the training database migration first")
    now = datetime.now(UTC)
    await session.execute(
        update(TrainingRun)
        .execution_options(synchronize_session=False)
        .where(
            TrainingRun.status.in_(("running", "cancel_requested")),
            or_(
                TrainingRun.lease_expires_at < now,
                TrainingRun.started_at
                < now - timedelta(seconds=get_settings().training_max_runtime_seconds),
            ),
        )
        .values(
            status="failed", error_code="worker_lease_expired", completed_at=now, lease_token=None
        )
    )
    await session.execute(
        update(TrainingRun)
        .execution_options(synchronize_session=False)
        .where(TrainingRun.status == "queued", TrainingRun.created_at < now - timedelta(days=1))
        .values(status="failed", error_code="queue_timeout", completed_at=now)
    )
    return control


def normalize_dataset(payload: TrainingConfig) -> dict[str, Any]:
    with TemporaryDirectory(prefix="opspilot-dataset-") as folder:
        path = Path(folder) / "input.jsonl"
        path.write_text(payload.dataset_jsonl, encoding="utf-8")
        try:
            examples = load_examples(path)
            if len(examples) > 1000:
                raise ValueError("Too many examples")
            splits = split_examples(examples)
        except ValueError as exc:
            raise HTTPException(
                422,
                "Invalid JSONL dataset: check fields, labels, conflicting duplicates "
                "and at least three independent group IDs",
            ) from exc
    result = payload.model_dump(mode="json", exclude={"request_id", "dataset_jsonl"})
    result.update(
        example_count=len(examples),
        model_id=MODEL_ID,
        model_revision=MODEL_REVISION,
        examples=[e.model_dump(mode="json") for e in examples],
        split_counts={key: len(value) for key, value in splits.items()},
    )
    return result


async def create_run(
    session: AsyncSession,
    *,
    org: uuid.UUID,
    user: uuid.UUID,
    request_id: uuid.UUID,
    payload: dict[str, Any],
) -> TrainingRun:
    enabled()
    if payload["method"] == "qlora" and not get_settings().training_qlora_enabled:
        raise HTTPException(422, "QLoRA is disabled. Configure a CUDA training worker first")
    await lock_control(session)
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    existing = await session.scalar(
        select(TrainingRun)
        .options(defer(TrainingRun.dataset))
        .where(TrainingRun.organization_id == org, TrainingRun.request_id == request_id)
    )
    if existing:
        if existing.payload_hash != digest:
            raise HTTPException(
                409, "This request ID already belongs to a different training configuration"
            )
        await session.commit()
        return existing
    active = await session.scalar(
        select(func.count())
        .select_from(TrainingRun)
        .where(TrainingRun.organization_id == org, TrainingRun.status.in_(ACTIVE))
    )
    total = await session.scalar(
        select(func.count()).select_from(TrainingRun).where(TrainingRun.status.in_(ACTIVE))
    )
    if active or (total or 0) >= 10:
        raise HTTPException(
            409, "One active run per organization and ten queued/running runs globally are allowed"
        )
    run = TrainingRun(
        organization_id=org,
        created_by_user_id=user,
        request_id=request_id,
        payload_hash=digest,
        name=payload["name"],
        payload={key: value for key, value in payload.items() if key != "examples"},
        dataset=payload["examples"],
        progress={"stage": "preparing", "completed_steps": 0, "epoch": 0},
        status="queued",
    )
    session.add(run)
    await session.commit()
    await session.refresh(run)
    return run


async def scoped_run(
    session: AsyncSession, org: uuid.UUID, run_id: uuid.UUID, *, with_dataset: bool = False
) -> TrainingRun:
    run = await session.scalar(
        select(TrainingRun)
        .options(*([] if with_dataset else [defer(TrainingRun.dataset)]))
        .where(TrainingRun.id == run_id, TrainingRun.organization_id == org)
        .execution_options(populate_existing=True)
    )
    if run is None:
        raise HTTPException(404, "Training run not found")
    return run


def view(run: TrainingRun) -> dict[str, Any]:
    return {
        "id": str(run.id),
        "name": run.name,
        "status": run.status,
        "method": run.payload["method"],
        "rank": run.payload["rank"],
        "epochs": run.payload["epochs"],
        "max_steps": run.payload["max_steps"],
        "max_tokens": run.payload["max_tokens"],
        "model_id": run.payload["model_id"],
        "model_revision": run.payload["model_revision"],
        "dataset_source": run.payload["dataset_source"],
        "example_count": run.payload["example_count"],
        "split_counts": run.payload["split_counts"],
        "progress": run.progress,
        "metrics": run.metrics,
        "error_code": run.error_code,
        "artifact_sha256": run.artifact_sha256 if run.status == "succeeded" else None,
        "artifact_bytes": run.artifact_bytes if run.status == "succeeded" else None,
        "created_at": run.created_at,
        "started_at": run.started_at,
        "completed_at": run.completed_at,
        "production_approved": False,
    }


async def claim(session: AsyncSession, device: str) -> dict[str, Any] | None:
    control = await lock_control(session)
    control.last_seen_at = datetime.now(UTC)
    control.device = device
    running = await session.scalar(
        select(func.count())
        .select_from(TrainingRun)
        .where(TrainingRun.status.in_(("running", "cancel_requested")))
    )
    if running:
        await session.commit()
        return None
    query = select(TrainingRun).where(TrainingRun.status == "queued")
    # Filtering JSON works on PostgreSQL and the lightweight SQL test database.
    if device != "cuda":
        query = query.where(TrainingRun.payload["method"].as_string() == "lora")
    run = await session.scalar(
        query.order_by(TrainingRun.created_at, TrainingRun.id).limit(1).with_for_update()
    )
    if not run:
        await session.commit()
        return None
    run.status = "running"
    run.started_at = datetime.now(UTC)
    run.lease_token = uuid.uuid4()
    run.lease_expires_at = datetime.now(UTC) + timedelta(seconds=LEASE_SECONDS)
    await session.commit()
    return {
        "id": str(run.id),
        "lease_token": str(run.lease_token),
        "payload": {**run.payload, "examples": run.dataset},
        "max_runtime_seconds": get_settings().training_max_runtime_seconds,
    }


async def leased_run(session: AsyncSession, run_id: uuid.UUID, lease: uuid.UUID) -> TrainingRun:
    await lock_control(session)
    run = await session.scalar(
        select(TrainingRun)
        .options(defer(TrainingRun.dataset))
        .where(TrainingRun.id == run_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if run is None or run.lease_token != lease or run.status not in ("running", "cancel_requested"):
        raise HTTPException(409, "Training lease is no longer valid")
    return run


async def heartbeat(
    session: AsyncSession, run_id: uuid.UUID, lease: uuid.UUID, progress: TrainingProgress
) -> dict[str, bool]:
    run = await leased_run(session, run_id, lease)
    if (
        progress.completed_steps < run.progress.get("completed_steps", 0)
        or progress.completed_steps > run.payload["max_steps"]
        or progress.epoch > run.payload["epochs"]
    ):
        raise HTTPException(422, "Invalid training progress")
    run.progress = progress.model_dump()
    run.lease_expires_at = datetime.now(UTC) + timedelta(seconds=LEASE_SECONDS)
    control = await session.get(TrainingControl, 1)
    assert control is not None
    control.last_seen_at = datetime.now(UTC)
    cancelled = run.status == "cancel_requested"
    await session.commit()
    return {"cancel_requested": cancelled}


async def finish(
    session: AsyncSession, run_id: uuid.UUID, lease: uuid.UUID, result: WorkerFinish
) -> TrainingRun:
    run = await leased_run(session, run_id, lease)
    if run.status == "cancel_requested":
        run.status = "cancelled"
    elif result.status == "succeeded":
        if not run.artifact_key or result.metrics is None:
            raise HTTPException(422, "Success requires an uploaded adapter and evaluation metrics")
        run.status = "succeeded"
        run.metrics = result.metrics.model_dump()
    else:
        run.status = result.status
    run.error_code = result.error_code if run.status == "failed" else None
    run.completed_at = datetime.now(UTC)
    run.lease_token = None
    run.lease_expires_at = None
    await session.commit()
    return run
