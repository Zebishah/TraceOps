"""Evaluate durable financial recovery health against alert thresholds.

This module creates structured alert decisions. It does not
send external notifications or execute financial actions.
"""

from dataclasses import dataclass

from ops_pilot.services.approval_recovery_health import (
    ApprovalRecoveryHealth,
)


@dataclass(frozen=True)
class RecoveryAlert:
    code: str
    severity: str
    actual: int
    threshold: int


def evaluate_recovery_alerts(
    *,
    health: ApprovalRecoveryHealth,
    quarantine_count_threshold: int,
    quarantine_age_threshold_seconds: int,
    processing_count_threshold: int,
) -> list[RecoveryAlert]:
    """Return all breached alert thresholds.

    An empty result means these particular thresholds were
    not exceeded; it does not prove the system is healthy.
    """
    if (
        min(
            quarantine_count_threshold,
            quarantine_age_threshold_seconds,
            processing_count_threshold,
        )
        < 1
    ):
        raise ValueError("Recovery alert thresholds must be positive")

    alerts: list[RecoveryAlert] = []

    if health.quarantined >= quarantine_count_threshold:
        alerts.append(
            RecoveryAlert(
                code="approval_recovery_quarantined_jobs",
                severity="critical",
                actual=health.quarantined,
                threshold=quarantine_count_threshold,
            )
        )

    age = health.oldest_quarantine_age_seconds

    if health.quarantined > 0 and age is not None and age >= quarantine_age_threshold_seconds:
        alerts.append(
            RecoveryAlert(
                code="approval_recovery_oldest_quarantine_age",
                severity="critical",
                actual=age,
                threshold=quarantine_age_threshold_seconds,
            )
        )

    if health.processing >= processing_count_threshold:
        alerts.append(
            RecoveryAlert(
                code="approval_recovery_processing_backlog",
                severity="warning",
                actual=health.processing,
                threshold=processing_count_threshold,
            )
        )

    return alerts
