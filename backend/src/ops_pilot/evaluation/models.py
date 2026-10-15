from enum import StrEnum

from pydantic import BaseModel, Field


class EvaluationStatus(StrEnum):
    PASSED = "passed"
    FAILED = "failed"


class EvaluationCheck(BaseModel):
    name: str
    passed: bool
    details: str | None = None


class EvaluationCaseResult(BaseModel):
    case_id: str
    status: EvaluationStatus
    checks: list[EvaluationCheck]


class EvaluationSuiteResult(BaseModel):
    suite_name: str
    total_cases: int = Field(ge=0)
    passed_cases: int = Field(ge=0)
    failed_cases: int = Field(ge=0)
    pass_rate: float = Field(
        ge=0.0,
        le=1.0,
    )
    cases: list[EvaluationCaseResult]
