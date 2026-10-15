import asyncio
import uuid
from dataclasses import dataclass

from ops_pilot.evaluation.models import (
    EvaluationCaseResult,
    EvaluationCheck,
    EvaluationStatus,
    EvaluationSuiteResult,
)
from ops_pilot.schemas.retrieval import RetrievalResult
from ops_pilot.services.retrieval import (
    retrieve_document_chunks,
)


@dataclass(frozen=True)
class RetrievalEvaluationCase:
    case_id: str
    query: str
    expected_terms: tuple[str, ...]


def _cases() -> list[RetrievalEvaluationCase]:
    return [
        RetrievalEvaluationCase(
            case_id="duplicate_payment_policy",
            query=("What should we do when a customer is charged twice?"),
            expected_terms=(
                "duplicate",
                "refund",
            ),
        ),
        RetrievalEvaluationCase(
            case_id="refund_approval_policy",
            query=("When is human approval required before issuing a refund?"),
            expected_terms=(
                "approval",
                "refund",
            ),
        ),
        RetrievalEvaluationCase(
            case_id="authentication_incident",
            query=("What should we investigate when a user cannot sign in?"),
            expected_terms=(
                "authentication",
                "sign",
            ),
        ),
    ]


def _contains_expected_terms(
    *,
    results: list[RetrievalResult],
    expected_terms: tuple[str, ...],
) -> bool:
    combined = " ".join(result.text.lower() for result in results)

    return all(term.lower() in combined for term in expected_terms)


async def evaluate_document_retrieval(
    *,
    organization_id: uuid.UUID,
) -> EvaluationSuiteResult:
    results: list[EvaluationCaseResult] = []

    for case in _cases():
        retrieved = await retrieve_document_chunks(
            organization_id=organization_id,
            query=case.query,
            limit=3,
        )

        has_results = bool(retrieved)

        expected_terms_present = (
            _contains_expected_terms(
                results=retrieved,
                expected_terms=case.expected_terms,
            )
            if retrieved
            else False
        )

        ranked_descending = all(
            retrieved[index].reranker_score >= retrieved[index + 1].reranker_score
            for index in range(len(retrieved) - 1)
        )

        passed = has_results and expected_terms_present and ranked_descending

        results.append(
            EvaluationCaseResult(
                case_id=case.case_id,
                status=(EvaluationStatus.PASSED if passed else EvaluationStatus.FAILED),
                checks=[
                    EvaluationCheck(
                        name="retrieval_has_results",
                        passed=has_results,
                        details=(f"count={len(retrieved)}"),
                    ),
                    EvaluationCheck(
                        name="expected_terms_present",
                        passed=expected_terms_present,
                        details=(f"expected_terms={list(case.expected_terms)}"),
                    ),
                    EvaluationCheck(
                        name="reranker_order",
                        passed=ranked_descending,
                        details=(f"scores={[result.reranker_score for result in retrieved]}"),
                    ),
                ],
            )
        )
        await asyncio.sleep(1.0)

    passed_cases = sum(result.status == EvaluationStatus.PASSED for result in results)

    total_cases = len(results)

    return EvaluationSuiteResult(
        suite_name="document_retrieval",
        total_cases=total_cases,
        passed_cases=passed_cases,
        failed_cases=total_cases - passed_cases,
        pass_rate=(passed_cases / total_cases if total_cases else 0.0),
        cases=results,
    )
