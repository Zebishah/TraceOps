from unittest.mock import AsyncMock

import pytest

import ops_pilot.inngest.functions.dispatch_recovery as module
from ops_pilot.services.background_dispatch_recovery import (
    RecoveryResult,
)


@pytest.mark.asyncio
async def test_recovery_schedule_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recovery = AsyncMock(
        return_value=RecoveryResult(
            candidates=3,
            attempted=2,
            failed=0,
        )
    )

    monkeypatch.setattr(
        module,
        "recover_abandoned_dispatches",
        recovery,
    )

    result = await module.run_dispatch_recovery()

    assert result == {
        "candidates": 3,
        "attempted": 2,
        "failed": 0,
    }

    recovery.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_recovery_schedule_reports_failures(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recovery = AsyncMock(
        return_value=RecoveryResult(
            candidates=2,
            attempted=2,
            failed=1,
        )
    )

    monkeypatch.setattr(
        module,
        "recover_abandoned_dispatches",
        recovery,
    )

    with pytest.raises(
        RuntimeError,
        match="failed for 1 jobs",
    ):
        await module.run_dispatch_recovery()

    recovery.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_recovery_schedule_empty_queue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recovery = AsyncMock(
        return_value=RecoveryResult(
            candidates=0,
            attempted=0,
            failed=0,
        )
    )

    monkeypatch.setattr(
        module,
        "recover_abandoned_dispatches",
        recovery,
    )

    result = await module.run_dispatch_recovery()

    assert result["attempted"] == 0
    assert result["failed"] == 0
