"""Tests for the approval recovery scheduler and registration."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

import ops_pilot.inngest.functions.approval_resume_recovery as recovery
import ops_pilot.main as main
from ops_pilot.services.approval_resume_processor import ResumeSweepResult
from ops_pilot.services.approval_resume_reconciliation import (
    ReconciliationResult,
)


@pytest.mark.parametrize(
    ("environment", "enabled", "expected"),
    [
        ("development", False, False),
        ("development", True, False),
        ("staging", False, False),
        ("staging", True, True),
        ("production", False, False),
        ("production", True, False),
    ],
)
def test_recovery_registration_is_staging_only(
    monkeypatch,
    environment,
    enabled,
    expected,
):
    settings = SimpleNamespace(
        app_name="OpsPilot Test",
        app_version="0.1.0",
        log_level="INFO",
        environment=environment,
        enable_approval_resume_cron=enabled,
    )

    monkeypatch.setattr(
        main,
        "get_settings",
        lambda: settings,
    )

    serve = Mock()

    monkeypatch.setattr(
        main.inngest.fast_api,
        "serve",
        serve,
    )

    main.create_app()

    serve.assert_called_once()

    registered = serve.call_args.args[2]

    found = main.recover_approval_resume_jobs in registered

    assert found is expected


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

    result = asyncio.run(recovery.run_approval_resume_recovery())

    assert result == {
        "claimed": 1,
        "completed": 1,
        "failed": 0,
        "quarantined": 2,
        "reconciled": 1,
        "unresolved": 1,
    }

    quarantine.assert_awaited_once()
    reconcile.assert_awaited_once()
    sweep.assert_awaited_once()


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
        "run_approval_resume_sweep",
        AsyncMock(
            return_value=ResumeSweepResult(
                claimed=1,
                completed=0,
                failed=1,
            )
        ),
    )

    with pytest.raises(
        RuntimeError,
        match="Approval resume sweep failed",
    ):
        asyncio.run(recovery.run_approval_resume_recovery())
