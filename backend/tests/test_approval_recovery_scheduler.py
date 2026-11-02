"""Tests for the approval recovery scheduler and registration."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

import ops_pilot.inngest.functions.approval_resume_recovery as recovery
import ops_pilot.main as main
from ops_pilot.services.approval_recovery_health import ApprovalRecoveryHealth
from ops_pilot.services.approval_resume_processor import ResumeSweepResult
from ops_pilot.services.approval_resume_reconciliation import (
    ReconciliationResult,
)


@pytest.mark.parametrize(
    (
        "environment",
        "staging_enabled",
        "production_enabled",
        "expected",
    ),
    [
        ("development", False, False, False),
        ("development", True, True, False),
        ("staging", False, False, False),
        ("staging", True, False, True),
        ("staging", False, True, False),
        ("production", False, False, False),
        ("production", True, False, False),
        ("production", False, True, True),
    ],
)
def test_recovery_registration_uses_environment_specific_flag(
    monkeypatch: pytest.MonkeyPatch,
    environment: str,
    staging_enabled: bool,
    production_enabled: bool,
    expected: bool,
) -> None:
    settings = SimpleNamespace(
        app_name="OpsPilot Test",
        app_version="0.1.0",
        log_level="INFO",
        environment=environment,
        enable_approval_resume_cron=staging_enabled,
        enable_production_approval_recovery=production_enabled,
    )

    monkeypatch.setattr(main, "get_settings", lambda: settings)

    serve = Mock()
    monkeypatch.setattr(main.inngest.fast_api, "serve", serve)

    main.create_app()

    serve.assert_called_once()
    registered = serve.call_args.args[2]

    assert (main.recover_approval_resume_jobs in registered) is expected


def test_recovery_coordinator_success(monkeypatch):
    quarantine = AsyncMock(return_value=2)

    reconcile = AsyncMock(
        return_value=ReconciliationResult(
            inspected=2,
            completed=1,
            unresolved=1,
        )
    )

    sweep = AsyncMock(
        return_value=ResumeSweepResult(
            claimed=1,
            completed=1,
            failed=0,
        )
    )

    monkeypatch.setattr(
        recovery,
        "quarantine_expired_resume_jobs",
        quarantine,
    )
    monkeypatch.setattr(
        recovery,
        "reconcile_quarantined_jobs",
        reconcile,
    )
    monkeypatch.setattr(
        recovery,
        "run_approval_resume_sweep",
        sweep,
    )
    monkeypatch.setattr(
        recovery,
        "get_settings",
        lambda: SimpleNamespace(
            approval_recovery_quarantine_alert_count=1,
            approval_recovery_quarantine_age_alert_seconds=3600,
            approval_recovery_processing_alert_count=25,
        ),
    )
    monkeypatch.setattr(
        recovery,
        "get_approval_recovery_health",
        AsyncMock(
            return_value=ApprovalRecoveryHealth(
                pending=0,
                processing=0,
                retryable_failed=0,
                quarantined=0,
                oldest_quarantine_age_seconds=None,
            )
        ),
    )
    result = asyncio.run(recovery.run_approval_resume_recovery())

    assert result == {
        "claimed": 1,
        "completed": 1,
        "failed": 0,
        "quarantined": 2,
        "reconciled": 1,
        "unresolved": 1,
        "quarantined_backlog": 0,
        "pending_backlog": 0,
        "processing_backlog": 0,
        "retryable_failed_backlog": 0,
        "oldest_quarantine_age_seconds": 0,
    }

    quarantine.assert_awaited_once()
    reconcile.assert_awaited_once()
    sweep.assert_awaited_once()


def test_successful_sweep_still_reports_existing_quarantine(
    monkeypatch,
    caplog,
):
    """A green sweep cannot conceal outstanding quarantined jobs."""

    monkeypatch.setattr(
        recovery,
        "quarantine_expired_resume_jobs",
        AsyncMock(return_value=0),
    )

    monkeypatch.setattr(
        recovery,
        "reconcile_quarantined_jobs",
        AsyncMock(
            return_value=ReconciliationResult(
                inspected=0,
                completed=0,
                unresolved=0,
            )
        ),
    )

    monkeypatch.setattr(
        recovery,
        "run_approval_resume_sweep",
        AsyncMock(
            return_value=ResumeSweepResult(
                claimed=0,
                completed=0,
                failed=0,
            )
        ),
    )

    monkeypatch.setattr(
        recovery,
        "get_approval_recovery_health",
        AsyncMock(
            return_value=ApprovalRecoveryHealth(
                pending=0,
                processing=0,
                retryable_failed=0,
                quarantined=2,
                oldest_quarantine_age_seconds=3600,
            )
        ),
    )

    with caplog.at_level("ERROR"):
        result = asyncio.run(recovery.run_approval_resume_recovery())

    assert result["failed"] == 0
    assert result["quarantined_backlog"] == 2
    assert result["oldest_quarantine_age_seconds"] == 3600

    assert "approval_recovery_quarantined_backlog" in caplog.text


def test_recovery_coordinator_reports_failure(monkeypatch):
    monkeypatch.setattr(
        recovery,
        "quarantine_expired_resume_jobs",
        AsyncMock(return_value=0),
    )
    monkeypatch.setattr(
        recovery,
        "reconcile_quarantined_jobs",
        AsyncMock(
            return_value=ReconciliationResult(
                inspected=0,
                completed=0,
                unresolved=0,
            )
        ),
    )
    monkeypatch.setattr(
        recovery,
        "get_settings",
        lambda: SimpleNamespace(
            approval_recovery_quarantine_alert_count=1,
            approval_recovery_quarantine_age_alert_seconds=3600,
            approval_recovery_processing_alert_count=25,
        ),
    )
    monkeypatch.setattr(
        recovery,
        "run_approval_resume_sweep",
        AsyncMock(
            return_value=ResumeSweepResult(
                claimed=1,
                completed=0,
                failed=1,
            )
        ),
    )

    # R05: Mock the database-backed health snapshot.
    # Unit tests must not connect to a real PostgreSQL database.
    monkeypatch.setattr(
        recovery,
        "get_approval_recovery_health",
        AsyncMock(
            return_value=ApprovalRecoveryHealth(
                pending=0,
                processing=0,
                retryable_failed=0,
                quarantined=1,
                oldest_quarantine_age_seconds=60,
            )
        ),
    )

    with pytest.raises(
        RuntimeError,
        match="Approval resume sweep failed",
    ):
        asyncio.run(recovery.run_approval_resume_recovery())
