import uuid

from fastapi import APIRouter

from ops_pilot.api.dependencies import CurrentMembership
from ops_pilot.schemas.answers import (
    AnswerRequest,
    AnswerResponse,
)
from ops_pilot.services.answers import answer_question

router = APIRouter(
    prefix="/organizations/{organization_id}/answers",
    tags=["answers"],
)


@router.post(
    "",
    response_model=AnswerResponse,
)
async def generate_answer(
    organization_id: uuid.UUID,
    request: AnswerRequest,
    membership: CurrentMembership,
) -> AnswerResponse:
    return await answer_question(
        organization_id=organization_id,
        question=request.question,
    )
