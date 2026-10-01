from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

from ops_pilot.core.config import get_settings
from ops_pilot.models.approval import ApprovalActionType
from ops_pilot.models.incident import (
    IncidentPriority,
    IncidentStatus,
)
from ops_pilot.schemas.approvals import (
    ApprovalResumeDecision,
)
from ops_pilot.schemas.incident_actions import (
    IncidentActionProposal,
)
from ops_pilot.schemas.incident_classification import IncidentCategory
from ops_pilot.schemas.retrieval import RetrievalResult
from ops_pilot.tools.schemas import (
    OperationalToolName,
    ToolCallRequest,
    ToolExecutionResult,
)


def get_checkpoint_database_url() -> str:
    database_url = get_settings().database_url

    if database_url.startswith(
        "postgresql+psycopg://",
    ):
        return database_url.replace(
            "postgresql+psycopg://",
            "postgresql://",
            1,
        )

    return database_url


def get_checkpoint_serializer() -> JsonPlusSerializer:
    return JsonPlusSerializer(
        pickle_fallback=False,
        allowed_msgpack_modules=[
            IncidentStatus,
            IncidentPriority,
            IncidentCategory,
            RetrievalResult,
            OperationalToolName,
            ToolCallRequest,
            ToolExecutionResult,
            ApprovalActionType,
            IncidentActionProposal,
            ApprovalResumeDecision,
        ],
    )


@asynccontextmanager
async def open_incident_checkpointer() -> AsyncIterator[AsyncPostgresSaver]:
    async with AsyncPostgresSaver.from_conn_string(
        get_checkpoint_database_url(),
        serde=get_checkpoint_serializer(),
    ) as checkpointer:
        yield checkpointer


async def setup_incident_checkpointer() -> None:
    async with open_incident_checkpointer() as checkpointer:
        await checkpointer.setup()
