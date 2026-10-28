"""D04/D08 document input and extraction security tests."""

from io import BytesIO

import pytest
from pypdf import PdfWriter

from ops_pilot.core.exceptions import UnsupportedDocumentTypeError
from ops_pilot.ingestion.extractors import (
    MAX_EXTRACTED_TEXT_CHARACTERS,
    MAX_PDF_PAGES,
    extract_pdf,
    extract_text_file,
)
from ops_pilot.services.documents import (
    normalize_document_filename,
    validate_document_signature,
)


@pytest.mark.parametrize(
    ("filename", "expected"),
    [
        ("../../secret.pdf", "secret.pdf"),
        (r"C:\temp\report.pdf", "report.pdf"),
        ("normal-report.pdf", "normal-report.pdf"),
        ("../notes.txt", "notes.txt"),
        ("", "document"),
        (".../", "document"),
    ],
)
def test_normalizes_unsafe_filenames(
    filename: str,
    expected: str,
) -> None:
    assert normalize_document_filename(filename) == expected


def test_rejects_fake_pdf() -> None:
    with pytest.raises(UnsupportedDocumentTypeError):
        validate_document_signature(
            mime_type="application/pdf",
            sample=b"This is not a PDF",
        )


def test_accepts_pdf_header() -> None:
    validate_document_signature(
        mime_type="application/pdf",
        sample=b"%PDF-1.7\n",
    )


def test_rejects_binary_text() -> None:
    with pytest.raises(UnsupportedDocumentTypeError):
        validate_document_signature(
            mime_type="text/plain",
            sample=b"hello\x00world",
        )


def test_rejects_unsupported_type() -> None:
    with pytest.raises(UnsupportedDocumentTypeError):
        validate_document_signature(
            mime_type="application/zip",
            sample=b"PK\x03\x04",
        )


def test_rejects_malformed_pdf() -> None:
    with pytest.raises(ValueError):
        extract_pdf(b"%PDF-1.7\nthis is not a valid PDF")


def test_rejects_pdf_with_excessive_pages() -> None:
    writer = PdfWriter()

    for _ in range(MAX_PDF_PAGES + 1):
        writer.add_blank_page(width=612, height=792)

    buffer = BytesIO()
    writer.write(buffer)

    with pytest.raises(ValueError, match="page count"):
        extract_pdf(buffer.getvalue())


def test_accepts_small_valid_pdf() -> None:
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)

    buffer = BytesIO()
    writer.write(buffer)

    extracted = extract_pdf(buffer.getvalue())

    assert extracted.pages == []


def test_rejects_excessive_extracted_text() -> None:
    with pytest.raises(ValueError, match="text limit"):
        extract_text_file(b"a" * (MAX_EXTRACTED_TEXT_CHARACTERS + 1))


def test_rejects_invalid_utf8_text() -> None:
    with pytest.raises(ValueError, match="UTF-8"):
        extract_text_file(b"hello\xffworld")


def test_rejects_binary_text_during_extraction() -> None:
    with pytest.raises(ValueError, match="binary content"):
        extract_text_file(b"hello\x00world")


def test_accepts_valid_text() -> None:
    result = extract_text_file(b"Hello OpsPilot!")

    assert len(result.pages) == 1
    assert result.pages[0].text == "Hello OpsPilot!"
    assert result.pages[0].page_number == 1
