"""Bounded document text extraction."""

import asyncio
import json
import logging
import sys
from io import BytesIO
from typing import Any

from pydantic import BaseModel
from pypdf import PdfReader

logger = logging.getLogger(__name__)

PDF_WALL_TIMEOUT_SECONDS = 20.0
MAX_PDF_WORKER_OUTPUT_BYTES = 32 * 1024 * 1024
MAX_EXTRACT_INPUT_BYTES = 10 * 1024 * 1024
MAX_PDF_PAGES = 100
MAX_EXTRACTED_TEXT_CHARACTERS = 2_000_000
MAX_PAGE_TEXT_CHARACTERS = 200_000
MAX_CONCURRENT_PDF_WORKERS = 2

_pdf_worker_semaphore = asyncio.Semaphore(MAX_CONCURRENT_PDF_WORKERS)


class ExtractedPage(BaseModel):
    page_number: int
    text: str


class ExtractedDocument(BaseModel):
    pages: list[ExtractedPage]


def _validate_input_size(data: bytes) -> None:
    if len(data) > MAX_EXTRACT_INPUT_BYTES:
        raise ValueError("Document exceeds extraction size limit")


def extract_pdf(data: bytes) -> ExtractedDocument:
    _validate_input_size(data)

    if not data.startswith(b"%PDF-"):
        raise ValueError("Invalid PDF signature")

    try:
        reader = PdfReader(BytesIO(data), strict=True)

        page_count = len(reader.pages)

        if page_count > MAX_PDF_PAGES:
            raise ValueError(f"PDF exceeds maximum page count of {MAX_PDF_PAGES}")

        pages: list[ExtractedPage] = []
        total_characters = 0

        for index, page in enumerate(reader.pages):
            # pypdf supports plain-text extraction, avoiding
            # the more expensive layout reconstruction mode.
            text = page.extract_text(extraction_mode="plain") or ""
            cleaned_text = text.strip()

            if len(cleaned_text) > MAX_PAGE_TEXT_CHARACTERS:
                raise ValueError("PDF page exceeds extraction text limit")

            total_characters += len(cleaned_text)

            if total_characters > MAX_EXTRACTED_TEXT_CHARACTERS:
                raise ValueError("PDF exceeds total extracted text limit")

            if cleaned_text:
                pages.append(
                    ExtractedPage(
                        page_number=index + 1,
                        text=cleaned_text,
                    )
                )

        return ExtractedDocument(pages=pages)

    except ValueError:
        raise
    except Exception as exc:
        raise ValueError("Unable to extract PDF document") from exc


def extract_text_file(data: bytes) -> ExtractedDocument:
    _validate_input_size(data)

    try:
        text = data.decode("utf-8").strip()
    except UnicodeDecodeError as exc:
        raise ValueError("Document is not valid UTF-8") from exc

    if len(text) > MAX_EXTRACTED_TEXT_CHARACTERS:
        raise ValueError("Document exceeds extracted text limit")

    if "\x00" in text:
        raise ValueError("Text document contains binary content")

    if not text:
        return ExtractedDocument(pages=[])

    return ExtractedDocument(
        pages=[
            ExtractedPage(
                page_number=1,
                text=text,
            )
        ]
    )


async def extract_pdf_isolated(
    data: bytes,
) -> ExtractedDocument:
    """Bound simultaneous PDF processes per application process."""

    _validate_input_size(data)

    async with _pdf_worker_semaphore:
        return await _extract_pdf_isolated_unlocked(data)


async def _extract_pdf_isolated_unlocked(
    data: bytes,
) -> ExtractedDocument:
    """Extract a PDF in a separate resource-limited process."""

    _validate_input_size(data)

    if not data.startswith(b"%PDF-"):
        raise ValueError("Invalid PDF signature")

    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "ops_pilot.ingestion.pdf_worker",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )

    try:
        try:
            stdout, _ = await asyncio.wait_for(
                process.communicate(input=data),
                timeout=PDF_WALL_TIMEOUT_SECONDS,
            )
        except TimeoutError as exc:
            raise ValueError("PDF extraction exceeded time limit") from exc

        if len(stdout) > MAX_PDF_WORKER_OUTPUT_BYTES:
            raise ValueError("PDF extraction output exceeds limit")

        if process.returncode != 0:
            logger.warning(
                "pdf_worker_failed",
                extra={"returncode": process.returncode},
            )
            raise ValueError("PDF extraction worker failed")

        try:
            response: Any = json.loads(stdout)
        except (ValueError, UnicodeDecodeError) as exc:
            raise ValueError("PDF worker returned an invalid response") from exc

        if (
            not isinstance(response, dict)
            or response.get("ok") is not True
            or not isinstance(response.get("document"), dict)
        ):
            raise ValueError("PDF worker returned an unsuccessful response")

        extracted = ExtractedDocument.model_validate(response["document"])

        if len(extracted.pages) > MAX_PDF_PAGES:
            raise ValueError("PDF exceeds page count limit")

        total_characters = 0

        for page in extracted.pages:
            if len(page.text) > MAX_PAGE_TEXT_CHARACTERS:
                raise ValueError("PDF page exceeds extracted text limit")

            total_characters += len(page.text)

            if total_characters > MAX_EXTRACTED_TEXT_CHARACTERS:
                raise ValueError("PDF exceeds total extracted text limit")

        return extracted

    finally:
        if process.returncode is None:
            try:
                process.kill()
            except ProcessLookupError:
                pass

        # Reap the child even when the extraction task
        # is being cancelled.
        await asyncio.shield(process.wait())


async def extract_document_text(
    *,
    data: bytes,
    mime_type: str,
) -> ExtractedDocument:
    _validate_input_size(data)

    if mime_type == "application/pdf":
        return await _extract_pdf_isolated_unlocked(data)

    if mime_type in {
        "text/plain",
        "text/markdown",
    }:
        return extract_text_file(data)

    raise ValueError(f"Unsupported MIME type: {mime_type}")
