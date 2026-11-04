"""Tenant-scoped dashboard reads. This router never executes financial recovery."""

import re
import uuid
from dataclasses import dataclass
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import String, cast, func, or_, select
from sqlalchemy.orm import InstrumentedAttribute
from sqlalchemy.sql.elements import ColumnElement
from sqlalchemy.sql.selectable import ScalarSelect

from ops_pilot.api.dependencies import CurrentMembership, DbSession
from ops_pilot.core.config import get_settings
from ops_pilot.db.base import Base
from ops_pilot.evaluation.reporting import load_organization_report
from ops_pilot.models.approval import ApprovalRequest
from ops_pilot.models.approval_resume_job import ApprovalResumeJob
from ops_pilot.models.automation_delivery import AutomationDelivery
from ops_pilot.models.background_job import BackgroundJob
from ops_pilot.models.customer import Customer
from ops_pilot.models.document import Document
from ops_pilot.models.incident import Incident
from ops_pilot.models.incident_memory import IncidentMemory
from ops_pilot.models.order import OperationalOrder
from ops_pilot.models.organization import Organization
from ops_pilot.models.payment_transaction import PaymentTransaction
from ops_pilot.schemas.approvals import ApprovalResponse
from ops_pilot.schemas.background_jobs import BackgroundJobResponse

router = APIRouter(prefix="/organizations/{organization_id}/dashboard", tags=["dashboard"])
Resource = Literal[
    "incidents",
    "documents",
    "approvals",
    "jobs",
    "customers",
    "orders",
    "payments",
    "memories",
    "automations",
    "recovery",
]


@dataclass(frozen=True)
class ResourceSpec:
    model: type[Base]
    fields: tuple[str, ...]
    search: tuple[str, ...] = ()
    statuses: tuple[str, ...] = ()


SPECS: dict[str, ResourceSpec] = {
    "incidents": ResourceSpec(
        Incident,
        (
            "id",
            "organization_id",
            "subject_customer_id",
            "title",
            "description",
            "status",
            "category",
            "priority",
            "created_at",
            "updated_at",
            "resolved_at",
            "resolution_reason",
        ),
        ("title", "description", "category"),
        ("new", "investigating", "awaiting_approval", "resolved", "failed"),
    ),
    "documents": ResourceSpec(
        Document,
        (
            "id",
            "organization_id",
            "original_filename",
            "mime_type",
            "size_bytes",
            "status",
            "failure_reason",
            "created_at",
            "updated_at",
            "active_index_generation",
        ),
        ("original_filename",),
        ("pending", "processing", "ready", "failed"),
    ),
    "approvals": ResourceSpec(
        ApprovalRequest,
        (
            "id",
            "organization_id",
            "incident_id",
            "action_type",
            "reason",
            "status",
            "decided_at",
            "executed_at",
            "created_at",
            "updated_at",
        ),
        ("reason",),
        ("pending", "approved", "rejected", "executed", "failed", "superseded"),
    ),
    "jobs": ResourceSpec(
        BackgroundJob,
        (
            "id",
            "organization_id",
            "job_type",
            "status",
            "resource_id",
            "progress_percent",
            "error_message",
            "started_at",
            "completed_at",
            "created_at",
            "updated_at",
        ),
        ("job_type", "error_message"),
        ("queued", "processing", "succeeded", "failed"),
    ),
    "customers": ResourceSpec(
        Customer,
        (
            "id",
            "organization_id",
            "external_customer_id",
            "full_name",
            "email",
            "created_at",
        ),
        ("external_customer_id", "full_name", "email"),
    ),
    "orders": ResourceSpec(
        OperationalOrder,
        (
            "id",
            "organization_id",
            "customer_id",
            "external_order_id",
            "product_name",
            "total_amount",
            "currency",
            "status",
            "ordered_at",
            "created_at",
        ),
        ("external_order_id", "product_name"),
        ("pending", "paid", "cancelled", "refunded"),
    ),
    "payments": ResourceSpec(
        PaymentTransaction,
        (
            "id",
            "organization_id",
            "order_id",
            "source_transaction_id",
            "external_transaction_id",
            "provider",
            "transaction_type",
            "amount",
            "currency",
            "status",
            "processed_at",
            "created_at",
        ),
        ("external_transaction_id", "provider"),
        ("pending", "succeeded", "failed", "refunded"),
    ),
    "memories": ResourceSpec(
        IncidentMemory,
        (
            "id",
            "organization_id",
            "incident_id",
            "subject_customer_id",
            "category",
            "summary",
            "resolution",
            "created_at",
            "updated_at",
        ),
        ("summary", "category"),
    ),
    "automations": ResourceSpec(
        AutomationDelivery,
        (
            "id",
            "organization_id",
            "event_type",
            "status",
            "attempt_count",
            "next_attempt_at",
            "last_error",
            "delivered_at",
            "created_at",
        ),
        ("event_type",),
        ("pending", "processing", "retry", "delivered", "dead"),
    ),
    "recovery": ResourceSpec(
        ApprovalResumeJob,
        (
            "id",
            "organization_id",
            "incident_id",
            "approval_request_id",
            "status",
            "attempts",
            "next_attempt_at",
            "lease_expires_at",
            "last_error",
            "completed_at",
            "created_at",
            "updated_at",
        ),
        ("last_error",),
        ("pending", "processing", "completed", "failed"),
    ),
}


class ResourcePage(BaseModel):
    items: list[dict[str, object]]
    total: int
    limit: int
    offset: int


class LatestInvestigation(BaseModel):
    job: BackgroundJobResponse | None
    approval: ApprovalResponse | None


class ProjectSearch(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    limit: int = Field(default=5, ge=1, le=10)


def sanitize_error(value: str) -> str:
    """Do not return provider URLs or possible credential values in delivery errors."""
    value = re.sub(r"https?://\S+", "[provider endpoint]", value)
    return re.sub(r"(?i)(token|secret|password|api[_-]?key)[=:]\s*\S+", r"\1=[redacted]", value)[
        :1000
    ]


def column(model: type[Base], name: str) -> InstrumentedAttribute[object]:
    attribute = getattr(model, name, None)
    if not isinstance(attribute, InstrumentedAttribute):
        raise ValueError("Unknown mapped dashboard column")
    return attribute


def public_row(row: object, fields: tuple[str, ...]) -> dict[str, object]:
    result: dict[str, object] = {name: getattr(row, name) for name in fields}
    for name in ("last_error", "error_message", "failure_reason"):
        value = result.get(name)
        if isinstance(value, str):
            result[name] = sanitize_error(value)
    return result


@router.get("/resources/{resource}", response_model=ResourcePage)
async def list_resource(
    organization_id: uuid.UUID,
    resource: Resource,
    membership: CurrentMembership,
    session: DbSession,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    q: str = Query(default="", max_length=200),
    status_filter: str | None = Query(default=None, alias="status", max_length=40),
    customer_id: uuid.UUID | None = None,
    incident_id: uuid.UUID | None = None,
    order_id: uuid.UUID | None = None,
) -> ResourcePage:
    spec = SPECS[resource]
    model = spec.model
    # Every query, including counts and optional joins, retains this predicate.
    predicates = [column(model, "organization_id") == organization_id]
    if status_filter:
        if status_filter not in spec.statuses:
            raise HTTPException(422, "Unsupported status for this resource")
        predicates.append(column(model, "status") == status_filter)
    if q.strip():
        escaped = q.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        predicates.append(
            or_(
                cast(column(model, "id"), String).ilike(f"%{escaped}%", escape="\\"),
                *[
                    getattr(model, field).ilike(f"%{escaped}%", escape="\\")
                    for field in spec.search
                ],
            )
        )
    if incident_id is not None:
        if resource not in {"approvals", "memories", "recovery"}:
            raise HTTPException(422, "Incident filter is not supported for this resource")
        predicates.append(column(model, "incident_id") == incident_id)
    if customer_id is not None:
        if resource == "orders":
            predicates.append(OperationalOrder.customer_id == customer_id)
        elif resource == "incidents" or resource == "memories":
            predicates.append(column(model, "subject_customer_id") == customer_id)
        elif resource == "payments":
            predicates.append(
                PaymentTransaction.order_id.in_(
                    select(OperationalOrder.id).where(
                        OperationalOrder.organization_id == organization_id,
                        OperationalOrder.customer_id == customer_id,
                    )
                )
            )
        else:
            raise HTTPException(422, "Customer filter is not supported for this resource")
    if order_id is not None:
        if resource != "payments":
            raise HTTPException(422, "Order filter is only supported for payments")
        predicates.append(PaymentTransaction.order_id == order_id)
    total = int(
        await session.scalar(select(func.count()).select_from(model).where(*predicates)) or 0
    )
    rows = (
        (
            await session.execute(
                select(model)
                .where(*predicates)
                .order_by(
                    column(model, "created_at").desc(),
                    column(model, "id").desc(),
                )
                .offset(offset)
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    items = [public_row(row, spec.fields) for row in rows]
    return ResourcePage(items=items, total=total, limit=limit, offset=offset)


@router.get("/resources/{resource}/{resource_id}", response_model=dict[str, object])
async def get_resource(
    organization_id: uuid.UUID,
    resource: Resource,
    resource_id: uuid.UUID,
    membership: CurrentMembership,
    session: DbSession,
) -> dict[str, object]:
    spec = SPECS[resource]
    result = await session.execute(
        select(spec.model).where(
            column(spec.model, "organization_id") == organization_id,
            column(spec.model, "id") == resource_id,
        )
    )
    row = result.scalars().first()
    if row is None:
        raise HTTPException(404, "Record not found")
    return public_row(row, spec.fields)


@router.get("/overview", response_model=dict[str, int])
async def overview(
    organization_id: uuid.UUID,
    membership: CurrentMembership,
    session: DbSession,
) -> dict[str, int]:
    def count(model: type[Base], *conditions: ColumnElement[bool]) -> ScalarSelect[int]:
        return (
            select(func.count())
            .select_from(model)
            .where(
                column(model, "organization_id") == organization_id,
                *conditions,
            )
            .scalar_subquery()
        )

    queries = {
        "incidents": count(Incident),
        "open_incidents": count(
            Incident, Incident.status.in_(["new", "investigating", "awaiting_approval"])
        ),
        "awaiting_approval": count(Incident, Incident.status == "awaiting_approval"),
        "pending_approvals": count(ApprovalRequest, ApprovalRequest.status == "pending"),
        "failed_jobs": count(BackgroundJob, BackgroundJob.status == "failed"),
        "pending_automation": count(
            AutomationDelivery,
            AutomationDelivery.status.in_(["pending", "retry", "processing"]),
        ),
        "documents": count(Document),
        "memories": count(IncidentMemory),
    }
    # One database round trip for the summary rather than one request per metric.
    result = (
        await session.execute(select(*[value.label(key) for key, value in queries.items()]))
    ).one()
    return {key: int(result[index]) for index, key in enumerate(queries)}


@router.get("/incidents/{incident_id}/latest", response_model=LatestInvestigation)
async def latest_investigation(
    organization_id: uuid.UUID,
    incident_id: uuid.UUID,
    membership: CurrentMembership,
    session: DbSession,
) -> LatestInvestigation:
    incident = await session.scalar(
        select(Incident.id).where(
            Incident.organization_id == organization_id,
            Incident.id == incident_id,
        )
    )
    if incident is None:
        raise HTTPException(404, "Incident not found")
    job = await session.scalar(
        select(BackgroundJob)
        .where(
            BackgroundJob.organization_id == organization_id,
            BackgroundJob.resource_id == incident_id,
            BackgroundJob.job_type == "incident_analysis",
        )
        .order_by(BackgroundJob.created_at.desc(), BackgroundJob.id.desc())
        .limit(1)
    )
    approval = await session.scalar(
        select(ApprovalRequest)
        .where(
            ApprovalRequest.organization_id == organization_id,
            ApprovalRequest.incident_id == incident_id,
        )
        .order_by(ApprovalRequest.created_at.desc(), ApprovalRequest.id.desc())
        .limit(1)
    )
    return LatestInvestigation(
        job=BackgroundJobResponse.model_validate(job) if job is not None else None,
        approval=ApprovalResponse.model_validate(approval) if approval is not None else None,
    )


@router.get("/workspace", response_model=dict[str, object])
async def workspace(
    organization_id: uuid.UUID,
    membership: CurrentMembership,
    session: DbSession,
) -> dict[str, object]:
    organization = await session.get(Organization, organization_id)
    if organization is None:
        raise HTTPException(404, "Organization not found")
    settings = get_settings()
    integrations = [
        {
            "name": "Groq",
            "role": "Classification, analysis and recommendations",
            "configured": bool(settings.groq_api_key),
            "model": settings.generation_model,
        },
        {
            "name": "Mistral",
            "role": "Document extraction and embeddings",
            "configured": bool(settings.mistral_api_key),
            "model": settings.embedding_model,
        },
        {
            "name": "Voyage",
            "role": "Evidence reranking",
            "configured": bool(settings.voyage_api_key),
            "model": settings.reranker_model,
        },
        {
            "name": "Inngest",
            "role": "Background jobs",
            "configured": bool(settings.inngest_event_key),
            "model": None,
        },
        {
            "name": "n8n",
            "role": "Optional automation delivery",
            "configured": bool(
                settings.n8n_delivery_enabled
                and settings.n8n_webhook_base_url
                and settings.n8n_webhook_secret
            ),
            "model": None,
        },
    ]
    return {
        "organization_id": organization.id,
        "name": organization.name,
        "slug": organization.slug,
        "role": membership.role,
        "environment": settings.environment,
        "integrations": integrations,
        "approval_execution_enabled": settings.approval_recovery_execution_enabled,
        "mcp_resource_url": str(settings.mcp_resource_url),
        "voice": {
            "enabled": settings.voice_enabled,
            "tts_enabled": settings.voice_tts_enabled,
            "transcription_model": settings.voice_transcription_model,
            "tts_voice": settings.voice_tts_voice,
        },
        "classifier": {
            "backend": settings.incident_classifier_backend,
            "finetuned_configured": bool(
                settings.finetuned_classifier_url and settings.finetuned_classifier_token
            ),
            "fallback_enabled": settings.finetuned_classifier_fallback_enabled,
            "release_id": settings.finetuned_classifier_release_id,
        },
    }


@router.post("/project-knowledge", response_model=list[dict[str, object]])
async def project_knowledge(
    payload: ProjectSearch, membership: CurrentMembership, session: DbSession
) -> list[dict[str, object]]:
    from ops_pilot.services.project_knowledge import search_project_knowledge

    await session.rollback()
    results = await search_project_knowledge(query=payload.query, limit=payload.limit)
    return [result.model_dump() for result in results]


@router.get("/evaluations", response_model=dict[str, object])
async def evaluation_report(
    organization_id: uuid.UUID, membership: CurrentMembership
) -> dict[str, object]:
    if str(membership.role) not in {"owner", "admin"}:
        raise HTTPException(403, "Evaluation reports require owner or admin role")
    # CurrentMembership already verifies the organization selected from /auth/me.
    try:
        return load_organization_report(membership.organization_id)
    except FileNotFoundError:
        raise HTTPException(
            404,
            "No evaluation report has been published for this workspace. "
            "Run scripts/run_evaluations.py; it discovers your organizations through /auth/me.",
        ) from None
    except (ValueError, OSError):
        raise HTTPException(500, "The workspace evaluation report could not be read") from None
