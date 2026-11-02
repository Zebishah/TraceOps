"""Regression tests for approval recovery execution gates and alerts."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import ops_pilot.inngest.functions.approval_resume_recovery as scheduler
from ops_pilot.services.approval_recovery_alerts import (
    evaluate_recovery_alerts,
)
from ops_pilot.services.approval_recovery_health import (
    ApprovalRecoveryHealth,
)


def settings(
    *,
    environment: str = "staging",
    execution_enabled: bool = False,
    staging_cron: bool = True,
    production_enabled: bool = False,
) -> SimpleNamespace:
    return SimpleNamespace(
        environment=environment,
        approval_recovery_execution_enabled=execution_enabled,
        enable_approval_resume_cron=staging_cron,
        enable_production_approval_recovery=production_enabled,
    )


@pytest.mark.anyio
async def test_disabled_execution_cannot_start_recovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        scheduler,
        "get_settings",
        lambda: settings(execution_enabled=False),
    )

    step = SimpleNamespace(run=AsyncMock())
    ctx = SimpleNamespace(step=step)

    result = await scheduler.execute_approval_recovery(ctx)

    assert result == {"skipped": 1}
    step.run.assert_not_awaited()


@pytest.mark.anyio
async def test_staging_can_execute_when_both_gates_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        scheduler,
        "get_settings",
        lambda: settings(execution_enabled=True),
    )

    expected = {"claimed": 0, "completed": 0, "failed": 0}
    step = SimpleNamespace(
        run=AsyncMock(return_value=expected),
    )
    ctx = SimpleNamespace(step=step)

    result = await scheduler.execute_approval_recovery(ctx)

    assert result == expected
    step.run.assert_awaited_once_with(
        "recover-approval-resumes",
        scheduler.run_approval_resume_recovery,
    )


@pytest.mark.anyio
async def test_production_execution_disabled_without_registration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        scheduler,
        "get_settings",
        lambda: settings(
            environment="production",
            execution_enabled=True,
            production_enabled=False,
        ),
    )

    step = SimpleNamespace(run=AsyncMock())
    ctx = SimpleNamespace(step=step)

    result = await scheduler.execute_approval_recovery(ctx)

    assert result == {"skipped": 1}
    step.run.assert_not_awaited()


def test_quarantined_backlog_produces_critical_alerts() -> None:
    health = ApprovalRecoveryHealth(
        pending=0,
        processing=0,
        retryable_failed=0,
        quarantined=2,
        oldest_quarantine_age_seconds=7200,
    )

    alerts = evaluate_recovery_alerts(
        health=health,
        quarantine_count_threshold=1,
        quarantine_age_threshold_seconds=3600,
        processing_count_threshold=25,
    )

    assert {alert.code for alert in alerts} == {
        "approval_recovery_quarantined_jobs",
        "approval_recovery_oldest_quarantine_age",
    }

    assert all(alert.severity == "critical" for alert in alerts)


def test_healthy_snapshot_produces_no_threshold_alerts() -> None:
    health = ApprovalRecoveryHealth(
        pending=0,
        processing=0,
        retryable_failed=0,
        quarantined=0,
        oldest_quarantine_age_seconds=None,
    )

    alerts = evaluate_recovery_alerts(
        health=health,
        quarantine_count_threshold=1,
        quarantine_age_threshold_seconds=3600,
        processing_count_threshold=25,
    )

    assert alerts == []


def test_processing_backlog_produces_warning() -> None:
    health = ApprovalRecoveryHealth(
        pending=0,
        processing=30,
        retryable_failed=0,
        quarantined=0,
        oldest_quarantine_age_seconds=None,
    )

    alerts = evaluate_recovery_alerts(
        health=health,
        quarantine_count_threshold=1,
        quarantine_age_threshold_seconds=3600,
        processing_count_threshold=25,
    )

    assert len(alerts) == 1
    assert alerts[0].code == "approval_recovery_processing_backlog"
    assert alerts[0].severity == "warning"


@pytest.mark.parametrize("threshold", [0, -1])
def test_invalid_thresholds_are_rejected(threshold: int) -> None:
    health = ApprovalRecoveryHealth(
        pending=0,
        processing=0,
        retryable_failed=0,
        quarantined=0,
        oldest_quarantine_age_seconds=None,
    )

    with pytest.raises(ValueError):
        evaluate_recovery_alerts(
            health=health,
            quarantine_count_threshold=threshold,
            quarantine_age_threshold_seconds=3600,
            processing_count_threshold=25,
        )


@pytest.mark.anyio
async def test_production_can_execute_with_both_gates_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        scheduler,
        "get_settings",
        lambda: settings(
            environment="production",
            execution_enabled=True,
            staging_cron=False,
            production_enabled=True,
        ),
    )

    expected = {
        "claimed": 1,
        "completed": 1,
        "failed": 0,
    }
    step = SimpleNamespace(run=AsyncMock(return_value=expected))
    ctx = SimpleNamespace(step=step)

    result = await scheduler.execute_approval_recovery(ctx)

    assert result == expected
    step.run.assert_awaited_once_with(
        "recover-approval-resumes",
        scheduler.run_approval_resume_recovery,
    )


@pytest.mark.anyio
async def test_production_kill_switch_blocks_registered_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        scheduler,
        "get_settings",
        lambda: settings(
            environment="production",
            execution_enabled=False,
            staging_cron=False,
            production_enabled=True,
        ),
    )

    step = SimpleNamespace(run=AsyncMock())
    ctx = SimpleNamespace(step=step)

    result = await scheduler.execute_approval_recovery(ctx)

    assert result == {"skipped": 1}
    step.run.assert_not_awaited()
