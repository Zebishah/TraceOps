"""Bounded browser and trusted-worker contracts; no shell commands or model URLs."""

import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class TrainingConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    request_id: uuid.UUID
    name: str = Field(min_length=1, max_length=100)
    method: Literal["lora", "qlora"] = "lora"
    rank: Literal[4, 8, 16] = 8
    epochs: int = Field(default=3, ge=1, le=5)
    max_steps: int = Field(default=50, ge=1, le=500)
    max_tokens: Literal[256, 512, 1024] = 512
    dataset_source: Literal["synthetic", "reviewed"] = "synthetic"
    deidentified: Literal[True]
    labels_reviewed: Literal[True]
    dataset_jsonl: str = Field(min_length=1, max_length=200000)

    @field_validator("dataset_jsonl")
    @classmethod
    def bounded_bytes(cls, value: str) -> str:
        if len(value.encode()) > 200000:
            raise ValueError("Dataset must be at most 200,000 UTF-8 bytes")
        return value


class RetryTraining(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: uuid.UUID


class WorkerClaim(BaseModel):
    model_config = ConfigDict(extra="forbid")
    device: Literal["cpu", "cuda"]


class TrainingProgress(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    stage: Literal["preparing", "loading", "training", "validating", "evaluating", "packaging"]
    completed_steps: int = Field(default=0, ge=0, le=500)
    epoch: int = Field(default=0, ge=0, le=5)
    validation_loss: float | None = Field(default=None, ge=0)


class TrainingMetrics(BaseModel):
    model_config = ConfigDict(extra="ignore", allow_inf_nan=False)
    total: int = Field(ge=1, le=1000)
    category_accuracy: float = Field(ge=0, le=1)
    priority_accuracy: float = Field(ge=0, le=1)
    joint_accuracy: float = Field(ge=0, le=1)
    invalid_outputs: int = Field(ge=0, le=1000)
    infrastructure_errors: int = Field(ge=0, le=1000)
    critical_misses: int = Field(ge=0, le=1000)
    high_risk_downgrades: int = Field(ge=0, le=1000)
    latency_p95_seconds: float | None = Field(default=None, ge=0)


class WorkerFinish(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["succeeded", "failed", "cancelled"]
    error_code: (
        Literal[
            "preparation_failed",
            "training_failed",
            "evaluation_failed",
            "packaging_failed",
            "worker_interrupted",
            "runtime_limit",
            "upload_failed",
        ]
        | None
    ) = None
    metrics: TrainingMetrics | None = None
