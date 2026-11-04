"""Admin training control and a separately authenticated, fenced worker protocol."""

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from tempfile import SpooledTemporaryFile
from typing import Annotated, Any, BinaryIO, cast

from anyio import to_thread
from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import defer

from ops_pilot.api.dependencies import (
    CurrentMembership,
    CurrentUser,
    DbSession,
    enforce_membership_role,
)
from ops_pilot.core.config import get_settings
from ops_pilot.models.membership import MembershipRole
from ops_pilot.models.training_run import TrainingRun
from ops_pilot.schemas.training import (
    RetryTraining,
    TrainingConfig,
    TrainingProgress,
    WorkerClaim,
    WorkerFinish,
)
from ops_pilot.services import training_runs as jobs
from ops_pilot.storage.s3 import S3Storage


def no_store(response: Response) -> None:
    response.headers["Cache-Control"] = "no-store"


async def admin(membership: CurrentMembership) -> None:
    enforce_membership_role(membership, frozenset({MembershipRole.OWNER, MembershipRole.ADMIN}))


async def worker(authorization: Annotated[str | None, Header()] = None) -> None:
    jobs.enabled()
    secret = get_settings().training_worker_token
    expected = secret.get_secret_value() if secret else ""
    if not expected or not secrets.compare_digest(
        (authorization or "").encode(), ("Bearer " + expected).encode()
    ):
        raise HTTPException(401, "Invalid training worker credential")


router = APIRouter(
    prefix="/organizations/{organization_id}/training",
    tags=["training"],
    dependencies=[Depends(admin), Depends(no_store)],
)
worker_router = APIRouter(
    prefix="/internal/training",
    tags=["training-worker"],
    dependencies=[Depends(worker), Depends(no_store)],
)
Lease = Annotated[uuid.UUID, Header(alias="X-Training-Lease")]


@router.get("/capabilities")
async def capabilities(organization_id: uuid.UUID, session: DbSession) -> dict[str, Any]:
    settings = get_settings()
    last_seen = None
    device = None
    if settings.training_enabled:
        control = await jobs.lock_control(session)
        last_seen, device = control.last_seen_at, control.device
        await session.commit()
    seen = last_seen.replace(tzinfo=UTC) if last_seen and last_seen.tzinfo is None else last_seen
    return {
        "enabled": settings.training_enabled,
        "qlora_enabled": settings.training_qlora_enabled,
        "model_id": jobs.MODEL_ID,
        "model_revision": jobs.MODEL_REVISION,
        "worker_online": seen is not None and seen > datetime.now(UTC) - timedelta(seconds=90),
        "worker_last_seen_at": last_seen,
        "worker_device": device,
        "max_dataset_bytes": 200000,
        "max_examples": 1000,
        "max_steps": 500,
        "max_runtime_seconds": settings.training_max_runtime_seconds,
    }


@router.post("/runs", status_code=202)
async def create(
    organization_id: uuid.UUID,
    payload: TrainingConfig,
    session: DbSession,
    current_user: CurrentUser,
) -> dict[str, Any]:
    jobs.enabled()
    run = await jobs.create_run(
        session,
        org=organization_id,
        user=current_user.id,
        request_id=payload.request_id,
        payload=jobs.normalize_dataset(payload),
    )
    return jobs.view(run)


@router.get("/runs")
async def listing(organization_id: uuid.UUID, session: DbSession) -> dict[str, Any]:
    jobs.enabled()
    await jobs.lock_control(session)
    rows = (
        (
            await session.execute(
                select(TrainingRun)
                .options(defer(TrainingRun.dataset))
                .where(TrainingRun.organization_id == organization_id)
                .order_by(TrainingRun.created_at.desc(), TrainingRun.id.desc())
                .limit(50)
            )
        )
        .scalars()
        .all()
    )
    result = {"items": [jobs.view(run) for run in rows]}
    await session.commit()
    return result


@router.get("/runs/{run_id}")
async def detail(
    organization_id: uuid.UUID, run_id: uuid.UUID, session: DbSession
) -> dict[str, Any]:
    jobs.enabled()
    await jobs.lock_control(session)
    result = jobs.view(await jobs.scoped_run(session, organization_id, run_id))
    await session.commit()
    return result


@router.post("/runs/{run_id}/cancel")
async def cancel(
    organization_id: uuid.UUID, run_id: uuid.UUID, session: DbSession
) -> dict[str, Any]:
    jobs.enabled()
    await jobs.lock_control(session)
    run = await jobs.scoped_run(session, organization_id, run_id)
    if run.status == "queued":
        run.status = "cancelled"
        run.completed_at = datetime.now(UTC)
    elif run.status == "running":
        run.status = "cancel_requested"
    await session.commit()
    return jobs.view(run)


@router.post("/runs/{run_id}/retry", status_code=202)
async def retry(
    organization_id: uuid.UUID,
    run_id: uuid.UUID,
    payload: RetryTraining,
    session: DbSession,
    current_user: CurrentUser,
) -> dict[str, Any]:
    jobs.enabled()
    original = await jobs.scoped_run(session, organization_id, run_id, with_dataset=True)
    if original.status not in ("failed", "cancelled"):
        raise HTTPException(409, "Only failed or cancelled runs can be retried")
    return jobs.view(
        await jobs.create_run(
            session,
            org=organization_id,
            user=current_user.id,
            request_id=payload.request_id,
            payload={**original.payload, "examples": original.dataset},
        )
    )


@router.get("/runs/{run_id}/download")
async def download(
    organization_id: uuid.UUID, run_id: uuid.UUID, session: DbSession
) -> dict[str, Any]:
    jobs.enabled()
    run = await jobs.scoped_run(session, organization_id, run_id)
    if run.status != "succeeded" or not run.artifact_key:
        raise HTTPException(409, "No completed adapter is available")
    storage = S3Storage()
    url = await to_thread.run_sync(
        lambda: storage.client.generate_presigned_url(
            "get_object",
            Params={
                "Bucket": storage.bucket_name,
                "Key": run.artifact_key,
                "ResponseContentDisposition": (
                    f'attachment; filename="opspilot-adapter-{run.id}.zip"'
                ),
            },
            ExpiresIn=60,
        )
    )
    return {
        "url": url,
        "sha256": run.artifact_sha256,
        "bytes": run.artifact_bytes,
        "expires_in": 60,
    }


@worker_router.post("/claim")
async def claim(payload: WorkerClaim, session: DbSession) -> dict[str, Any]:
    return {"job": await jobs.claim(session, payload.device)}


@worker_router.post("/runs/{run_id}/heartbeat")
async def heartbeat(
    run_id: uuid.UUID, lease: Lease, payload: TrainingProgress, session: DbSession
) -> dict[str, bool]:
    return await jobs.heartbeat(session, run_id, lease, payload)


@worker_router.post("/runs/{run_id}/finish")
async def finish(
    run_id: uuid.UUID, lease: Lease, payload: WorkerFinish, session: DbSession
) -> dict[str, Any]:
    return jobs.view(await jobs.finish(session, run_id, lease, payload))


@worker_router.put("/runs/{run_id}/artifact")
async def artifact(
    run_id: uuid.UUID, lease: Lease, request: Request, session: DbSession
) -> dict[str, Any]:
    run = await jobs.leased_run(session, run_id, lease)
    if run.status != "running":
        raise HTTPException(409, "Training cancellation is pending")
    key = f"training/{run.organization_id}/{run_id}/{lease}/adapter.zip"
    await session.commit()  # Never hold the database mutex while receiving/uploading a file.
    digest = hashlib.sha256()
    size = 0
    prefix = b""
    with SpooledTemporaryFile(max_size=1024 * 1024, mode="w+b") as output:
        async for chunk in request.stream():
            size += len(chunk)
            if size > jobs.MAX_ARTIFACT_BYTES:
                raise HTTPException(413, "Adapter ZIP exceeds 64 MiB")
            digest.update(chunk)
            if len(prefix) < 4:
                prefix = (prefix + chunk)[:4]
            output.write(chunk)
        if prefix != b"PK\x03\x04":
            raise HTTPException(422, "Expected an adapter ZIP")
        output.seek(0)
        storage = S3Storage()
        try:
            await storage.upload_file(
                file=cast(BinaryIO, output), key=key, content_type="application/zip"
            )
            run = await jobs.leased_run(session, run_id, lease)
            if run.status != "running":
                raise HTTPException(409, "Training cancellation is pending")
            run.artifact_key, run.artifact_sha256, run.artifact_bytes = (
                key,
                digest.hexdigest(),
                size,
            )
            await session.commit()
        except BaseException:
            await session.rollback()
            await storage.delete_file(key=key)
            raise
    return {"sha256": digest.hexdigest(), "bytes": size}
