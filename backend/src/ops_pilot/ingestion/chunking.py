import uuid

from langchain_text_splitters import RecursiveCharacterTextSplitter

from ops_pilot.ingestion.extractors import ExtractedPage
from ops_pilot.schemas.chunks import DocumentChunk

CHUNK_SIZE = 1000
CHUNK_OVERLAP = 150


def create_document_chunks(
    *,
    pages: list[ExtractedPage],
    organization_id: uuid.UUID,
    document_id: uuid.UUID,
    source_filename: str,
    document_checksum: str,
) -> list[DocumentChunk]:
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        length_function=len,
        separators=[
            "\n\n",
            "\n",
            ". ",
            " ",
            "",
        ],
    )

    chunks: list[DocumentChunk] = []

    chunk_index = 0

    for page in pages:
        pieces = splitter.split_text(
            page.text,
        )

        for piece in pieces:
            cleaned_text = piece.strip()

            if not cleaned_text:
                continue

            chunk_id = uuid.uuid5(
                document_id,
                f"page:{page.page_number}:chunk:{chunk_index}",
            )

            chunks.append(
                DocumentChunk(
                    id=chunk_id,
                    organization_id=organization_id,
                    document_id=document_id,
                    chunk_index=chunk_index,
                    page_number=page.page_number,
                    text=cleaned_text,
                    source_filename=source_filename,
                    document_checksum=document_checksum,
                )
            )

            chunk_index += 1

    return chunks
