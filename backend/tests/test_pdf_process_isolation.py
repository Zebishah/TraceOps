"""D04/D08: PDF extraction subprocess safety."""

import asyncio
import sys
from io import BytesIO
from unittest.mock import call

import pytest
from pypdf import PdfWriter

import ops_pilot.ingestion.extractors as extractors
from ops_pilot.ingestion.pdf_worker import (
    PDF_CPU_LIMIT_SECONDS,
    PDF_MEMORY_LIMIT_BYTES,
    apply_resource_limits,
)


def valid_pdf_bytes() -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)

    buffer = BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


@pytest.mark.anyio
async def test_valid_pdf_uses_isolated_worker() -> None:
    result = await extractors.extract_document_text(
        data=valid_pdf_bytes(),
        mime_type="application/pdf",
    )

    assert result.pages == []


@pytest.mark.anyio
async def test_malformed_pdf_is_rejected_by_child() -> None:
    with pytest.raises(ValueError, match="PDF extraction worker failed"):
        await extractors.extract_document_text(
            data=b"%PDF-1.7\nnot a real PDF",
            mime_type="application/pdf",
        )


@pytest.mark.anyio
async def test_pdf_worker_timeout_kills_child(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_create = asyncio.create_subprocess_exec
    launched = []

    async def fake_create(*args, **kwargs):
        # Simulate a hung PDF parser using a real child process.
        process = await real_create(
            sys.executable,
            "-c",
            "import time; time.sleep(60)",
            **kwargs,
        )
        launched.append(process)
        return process

    monkeypatch.setattr(
        extractors.asyncio,
        "create_subprocess_exec",
        fake_create,
    )

    monkeypatch.setattr(
        extractors,
        "PDF_WALL_TIMEOUT_SECONDS",
        0.05,
    )

    with pytest.raises(ValueError, match="time limit"):
        await extractors.extract_pdf_isolated(valid_pdf_bytes())

    assert len(launched) == 1
    assert launched[0].returncode is not None


def test_worker_applies_linux_resource_limits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import resource

    calls = []

    monkeypatch.setattr(
        resource,
        "setrlimit",
        lambda name, limits: calls.append(call(name, limits)),
    )

    apply_resource_limits()

    assert (
        call(
            resource.RLIMIT_AS,
            (PDF_MEMORY_LIMIT_BYTES, PDF_MEMORY_LIMIT_BYTES),
        )
        in calls
    )

    assert (
        call(
            resource.RLIMIT_CPU,
            (PDF_CPU_LIMIT_SECONDS, PDF_CPU_LIMIT_SECONDS + 1),
        )
        in calls
    )

    assert call(resource.RLIMIT_FSIZE, (0, 0)) in calls
    assert call(resource.RLIMIT_CORE, (0, 0)) in calls


@pytest.mark.anyio
async def test_text_extraction_does_not_spawn_pdf_worker(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def forbidden_process(*args, **kwargs):
        raise AssertionError("Text extraction must not spawn a PDF process")

    monkeypatch.setattr(
        extractors.asyncio,
        "create_subprocess_exec",
        forbidden_process,
    )

    result = await extractors.extract_document_text(
        data=b"Hello OpsPilot!",
        mime_type="text/plain",
    )

    assert result.pages[0].text == "Hello OpsPilot!"


@pytest.mark.anyio
async def test_pdf_worker_concurrency_is_bounded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    active = 0
    maximum_active = 0

    async def fake_unlocked(data: bytes):
        nonlocal active, maximum_active

        active += 1
        maximum_active = max(maximum_active, active)

        try:
            await asyncio.sleep(0.02)
            return extractors.ExtractedDocument(pages=[])
        finally:
            active -= 1

    monkeypatch.setattr(
        extractors,
        "_extract_pdf_isolated_unlocked",
        fake_unlocked,
    )

    results = await asyncio.gather(
        *[extractors.extract_pdf_isolated(valid_pdf_bytes()) for _ in range(8)]
    )

    assert len(results) == 8
    assert maximum_active <= extractors.MAX_CONCURRENT_PDF_WORKERS
    assert maximum_active >= 1


@pytest.mark.anyio
async def test_pdf_worker_cancellation_terminates_child(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real_create = asyncio.create_subprocess_exec
    launched = []
    child_started = asyncio.Event()

    async def fake_create(*args, **kwargs):
        process = await real_create(
            sys.executable,
            "-c",
            "import time; time.sleep(60)",
            **kwargs,
        )

        launched.append(process)
        child_started.set()
        return process

    monkeypatch.setattr(
        extractors.asyncio,
        "create_subprocess_exec",
        fake_create,
    )

    task = asyncio.create_task(extractors.extract_pdf_isolated(valid_pdf_bytes()))

    await asyncio.wait_for(child_started.wait(), timeout=5)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task

    assert len(launched) == 1

    # Child reaping must finish, even if the parent task
    # has already propagated cancellation.
    await asyncio.wait_for(launched[0].wait(), timeout=5)

    assert launched[0].returncode is not None
