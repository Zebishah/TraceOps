import uuid

from ops_pilot.ingestion.chunking import (
    create_document_chunks,
)
from ops_pilot.ingestion.extractors import ExtractedPage


def test_create_document_chunks() -> None:
    organization_id = uuid.uuid4()
    document_id = uuid.uuid4()

    pages = [
        ExtractedPage(
            page_number=1,
            text="A" * 2500,
        )
    ]

    chunks = create_document_chunks(
        pages=pages,
        organization_id=organization_id,
        document_id=document_id,
        source_filename="test.txt",
        document_checksum="abc123",
    )

    assert len(chunks) > 1

    for chunk in chunks:
        assert chunk.organization_id == organization_id
        assert chunk.document_id == document_id
        assert chunk.source_filename == "test.txt"
        assert chunk.document_checksum == "abc123"
        assert chunk.page_number == 1


def test_chunk_ids_are_deterministic() -> None:
    organization_id = uuid.uuid4()
    document_id = uuid.uuid4()

    pages = [
        ExtractedPage(
            page_number=1,
            text="Hello world. " * 300,
        )
    ]

    kwargs = {
        "pages": pages,
        "organization_id": organization_id,
        "document_id": document_id,
        "source_filename": "test.txt",
        "document_checksum": "abc123",
    }

    first = create_document_chunks(**kwargs)
    second = create_document_chunks(**kwargs)

    assert [chunk.id for chunk in first] == [chunk.id for chunk in second]


def test_empty_pages_produce_no_chunks() -> None:
    chunks = create_document_chunks(
        pages=[],
        organization_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        source_filename="empty.txt",
        document_checksum="abc123",
    )

    assert chunks == []


def test_chunks_preserve_page_numbers() -> None:
    pages = [
        ExtractedPage(
            page_number=1,
            text="First page content. " * 100,
        ),
        ExtractedPage(
            page_number=2,
            text="Second page content. " * 100,
        ),
    ]

    chunks = create_document_chunks(
        pages=pages,
        organization_id=uuid.uuid4(),
        document_id=uuid.uuid4(),
        source_filename="test.pdf",
        document_checksum="abc123",
    )

    page_numbers = {chunk.page_number for chunk in chunks}

    assert page_numbers == {1, 2}
