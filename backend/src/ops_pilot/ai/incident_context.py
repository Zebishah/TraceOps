from ops_pilot.schemas.retrieval import RetrievalResult
from ops_pilot.tools.schemas import ToolExecutionResult


def format_incident_evidence(
    evidence: list[RetrievalResult],
) -> str:
    if not evidence:
        return "No supporting document evidence was retrieved."

    parts: list[str] = []

    for index, result in enumerate(evidence, start=1):
        parts.append(
            f"[SOURCE {index}]\n"
            f"File: {result.source_filename}\n"
            f"Page: {result.page_number}\n"
            f"Text:\n{result.text}"
        )

    return "\n\n".join(parts)


def format_tool_results(
    results: list[ToolExecutionResult],
) -> str:
    if not results:
        return "No operational tool results were collected."

    parts: list[str] = []

    for index, result in enumerate(results, start=1):
        parts.append(
            f"[TOOL {index}]\n"
            f"Tool: {result.tool_name.value}\n"
            f"Success: {result.success}\n"
            f"Result:\n{result.content}"
        )

    return "\n\n".join(parts)
