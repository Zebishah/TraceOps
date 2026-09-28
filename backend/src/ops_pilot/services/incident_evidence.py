import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from ops_pilot.models.incident import Incident
from ops_pilot.schemas.retrieval import RetrievalResult
from ops_pilot.services.incidents import get_incident
from ops_pilot.services.retrieval import retrieve_document_chunks


def build_incident_retrieval_query(
    incident: Incident,
) -> str:
    parts = [
        incident.title,
        incident.description,
    ]

    if incident.category is not None:
        parts.append(
            f"Incident category: {incident.category}",
        )

    return "\n".join(parts)


async def retrieve_incident_evidence(
    *,
    session: AsyncSession,
    organization_id: uuid.UUID,
    incident_id: uuid.UUID,
    limit: int = 5,
) -> tuple[str, list[RetrievalResult]]:
    incident = await get_incident(
        session=session,
        organization_id=organization_id,
        incident_id=incident_id,
    )

    query = build_incident_retrieval_query(
        incident,
    )

    evidence = await retrieve_document_chunks(
        organization_id=organization_id,
        query=query,
        limit=limit,
    )

    return query, evidence
