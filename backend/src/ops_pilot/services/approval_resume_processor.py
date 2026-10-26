"""Execute durable approval-resume jobs.

Only this worker resumes approval-gated LangGraph workflows.
"""

import asyncio
import logging
from dataclasses import dataclass

from langchain_core.runnables import RunnableConfig
from langgraph.types import Command
from sqlalchemy import select

from ops_pilot.db.session import async_session_factory
from ops_pilot.models.approval import ApprovalRequest, ApprovalStatus
from ops_pilot.models.incident import Incident, IncidentStatus
from ops_pilot.schemas.approvals import ApprovalResumeDecision
from ops_pilot.services.approval_resume_recovery import (
    ClaimedResumeJob,
    claim_resume_jobs,
    complete_resume_job,
    fail_resume_job,
    renew_resume_job_lease,
)
from ops_pilot.workflows.incident.checkpointing import (
    open_incident_checkpointer,
)
from ops_pilot.workflows.incident.graph import (
    build_incident_investigation_graph,
)
from ops_pilot.workflows.incident.state import IncidentGraphContext

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ResumeSweepResult:
    claimed: int
    completed: int
    failed: int


async def process_claimed_resume_job(
    job: ClaimedResumeJob,
) -> None:
    """Resume one approval or verify an already completed execution."""

    # Load from DB instead of trusting potentially stale event data.
    async with async_session_factory() as session:
        approval_result = await session.execute(
            select(ApprovalRequest).where(
                ApprovalRequest.id == job.approval_request_id,
                ApprovalRequest.organization_id == job.organization_id,
                ApprovalRequest.incident_id == job.incident_id,
            )
        )

        approval = approval_result.scalar_one_or_none()

        incident_result = await session.execute(
            select(Incident).where(
                Incident.id == job.incident_id,
                Incident.organization_id == job.organization_id,
            )
        )
        incident = incident_result.scalar_one_or_none()

        if approval is None or incident is None:
            raise RuntimeError("Approval or incident not found")

        approval_status = approval.status
        reviewer_id = approval.decided_by_user_id
        decision_comment = approval.decision_comment
        thread_id = approval.workflow_thread_id

        if approval_status not in {
            ApprovalStatus.APPROVED,
            ApprovalStatus.REJECTED,
            ApprovalStatus.EXECUTED,
        }:
            raise RuntimeError("Approval has no recorded final decision")

        if reviewer_id is None:
            raise RuntimeError("Approval lacks a recorded reviewer identity")

        # Do not resume a workflow after manual resolution.
        # An already executed refund is handled by checkpoint
        # verification below, without replaying the action.
        if (
            incident.status == IncidentStatus.RESOLVED
            and approval_status != ApprovalStatus.EXECUTED
        ):
            raise RuntimeError("Incident resolved without completed refund execution")

        # Release read transaction before running the graph.
        await session.rollback()

    config: RunnableConfig = {
        "configurable": {
            "thread_id": thread_id,
        }
    }

    async with open_incident_checkpointer() as checkpointer:
        graph = build_incident_investigation_graph(
            checkpointer=checkpointer,
        )

        snapshot = await graph.aget_state(config)

        paused_at_gate = any(
            task.name == "approval_gate" and bool(task.interrupts) for task in snapshot.tasks
        )

        # A prior execution may have completed but failed
        # to mark its durable job as completed.
        if not paused_at_gate:
            await verify_terminal_checkpoint(
                graph=graph,
                config=config,
                approval_status=approval_status,
            )
            return

        # If a refund was already recorded, an approval-gate
        # replay is unexpected and must be investigated.
        if approval_status == ApprovalStatus.EXECUTED:
            raise RuntimeError("Executed approval is still paused at approval gate")

        decision = ApprovalResumeDecision(
            approval_request_id=job.approval_request_id,
            approved=(approval_status == ApprovalStatus.APPROVED),
            decided_by_user_id=reviewer_id,
            comment=decision_comment,
        )

        # Use a fresh session for actual graph execution.
        async with async_session_factory() as session:
            try:
                await graph.ainvoke(
                    Command(resume=decision.model_dump(mode="json")),
                    config=config,
                    context=IncidentGraphContext(session=session),
                )
            except BaseException:
                await session.rollback()
                raise

        # Re-read approval state and checkpoint after execution.
        async with async_session_factory() as session:
            fresh_result = await session.execute(
                select(ApprovalRequest).where(
                    ApprovalRequest.id == job.approval_request_id,
                    ApprovalRequest.organization_id == job.organization_id,
                    ApprovalRequest.incident_id == job.incident_id,
                )
            )
            fresh = fresh_result.scalar_one_or_none()

            if fresh is None:
                raise RuntimeError("Approval disappeared after workflow execution")

            final_status = fresh.status
            await session.rollback()

        await verify_terminal_checkpoint(
            graph=graph,
            config=config,
            approval_status=final_status,
        )


async def verify_terminal_checkpoint(
    *,
    graph: object,
    config: RunnableConfig,
    approval_status: ApprovalStatus,
) -> None:
    """Require a terminal checkpoint and a verified final outcome."""

    # Runtime supports this method; the exact graph typing is
    # intentionally kept out of our service API here.
    from typing import Any, cast

    runnable = cast(Any, graph)
    snapshot = await runnable.aget_state(config)

    if snapshot.next or snapshot.tasks:
        raise RuntimeError("Approval workflow has not reached a terminal checkpoint")

    values = snapshot.values or {}

    if approval_status == ApprovalStatus.EXECUTED:
        if values.get("refund_verified") is not True:
            raise RuntimeError("Refund approval completed without verification")
        return

    if approval_status == ApprovalStatus.REJECTED:
        decision = values.get("approval_decision")

        if decision is None:
            raise RuntimeError("Rejected approval lacks checkpoint decision")

        approved = (
            decision.get("approved")
            if isinstance(decision, dict)
            else getattr(decision, "approved", None)
        )

        if approved is not False:
            raise RuntimeError("Checkpoint does not show rejection")

        return

    raise RuntimeError("Approval workflow is not in a verified terminal state")


async def keep_resume_job_lease_alive(
    *,
    job: ClaimedResumeJob,
    stop: asyncio.Event,
    owner: asyncio.Task[object],
    interval_seconds: float = 30,
) -> None:
    """Renew the approval job lease while processing."""

    while not stop.is_set():
        try:
            await asyncio.wait_for(
                stop.wait(),
                timeout=interval_seconds,
            )
            return
        except TimeoutError:
            pass

        try:
            renewed = await renew_resume_job_lease(
                job=job,
            )
        except Exception:
            logger.exception(
                "approval_resume_lease_renewal_failed",
                extra={"job_id": str(job.id)},
            )
            owner.cancel()
            return

        if not renewed:
            logger.error(
                "approval_resume_lease_lost",
                extra={"job_id": str(job.id)},
            )
            owner.cancel()
            return


async def run_approval_resume_sweep() -> ResumeSweepResult:
    """Process one durable approval job with lease renewal."""

    claimed_jobs = await claim_resume_jobs(limit=1)

    completed = 0
    failed = 0

    for job in claimed_jobs:
        owner = asyncio.current_task()

        if owner is None:
            raise RuntimeError("Approval worker requires an asyncio task")

        stop = asyncio.Event()

        heartbeat = asyncio.create_task(
            keep_resume_job_lease_alive(
                job=job,
                stop=stop,
                owner=owner,
            )
        )

        try:
            await process_claimed_resume_job(job)

            # Check ownership again before completion.
            owns_lease = await renew_resume_job_lease(job=job)

            if not owns_lease:
                raise RuntimeError("Approval worker lost its lease")

            completed_ok = await complete_resume_job(job=job)

            if not completed_ok:
                raise RuntimeError("Unable to complete approval resume job")

            completed += 1

        except asyncio.CancelledError:
            # Never retry an uncertain financial operation blindly.
            logger.warning(
                "approval_resume_worker_cancelled",
                extra={"job_id": str(job.id)},
            )
            raise

        except Exception as exc:
            failed += 1

            logger.exception(
                "approval_resume_job_failed",
                extra={
                    "job_id": str(job.id),
                    "approval_id": str(job.approval_request_id),
                },
            )

            await fail_resume_job(
                job=job,
                error=f"{type(exc).__name__}: {exc}",
                terminal=True,
            )

        finally:
            stop.set()

            heartbeat.cancel()

            try:
                await heartbeat
            except asyncio.CancelledError:
                pass

    return ResumeSweepResult(
        claimed=len(claimed_jobs),
        completed=completed,
        failed=failed,
    )
