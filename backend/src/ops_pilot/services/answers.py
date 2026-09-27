import re
import uuid

from ops_pilot.ai.generation import generate_grounded_answer
from ops_pilot.schemas.answers import AnswerResponse, Citation
from ops_pilot.services.retrieval import retrieve_document_chunks

SOURCE_PATTERN = re.compile(r"\[SOURCE\s+(\d+)\]")


def get_used_source_numbers(answer: str) -> list[int]:
    matches = SOURCE_PATTERN.findall(answer)

    source_numbers: list[int] = []

    for match in matches:
        source_number = int(match)

        if source_number not in source_numbers:
            source_numbers.append(source_number)

    return source_numbers


async def answer_question(
    *,
    organization_id: uuid.UUID,
    question: str,
) -> AnswerResponse:
    results = await retrieve_document_chunks(
        organization_id=organization_id,
        query=question,
        limit=5,
    )

    if not results:
        return AnswerResponse(
            question=question,
            answer=("I could not find enough evidence in the organization's documents."),
            citations=[],
        )

    context_parts: list[str] = []
    available_citations: dict[int, Citation] = {}

    for index, result in enumerate(results, start=1):
        context_parts.append(
            f"[SOURCE {index}]\n"
            f"File: {result.source_filename}\n"
            f"Page: {result.page_number}\n"
            f"Text:\n{result.text}"
        )

        available_citations[index] = Citation(
            source_number=index,
            document_id=result.document_id,
            chunk_id=result.chunk_id,
            source_filename=result.source_filename,
            page_number=result.page_number,
        )

    context = "\n\n".join(context_parts)

    answer = await generate_grounded_answer(
        question=question,
        context=context,
    )

    used_source_numbers = get_used_source_numbers(answer)

    invalid_sources = [
        source_number
        for source_number in used_source_numbers
        if source_number not in available_citations
    ]

    if invalid_sources:
        raise RuntimeError(f"LLM referenced invalid sources: {invalid_sources}")

    citations = [available_citations[source_number] for source_number in used_source_numbers]

    return AnswerResponse(
        question=question,
        answer=answer,
        citations=citations,
    )
