from io import BytesIO

from anyio import to_thread
from pydantic import BaseModel
from pypdf import PdfReader


class ExtractedPage(BaseModel):
    page_number: int
    text: str


class ExtractedDocument(BaseModel):
    pages: list[ExtractedPage]


async def extract_pdf_text(data: bytes) -> str:
    def extract() -> str:
        reader = PdfReader(BytesIO(data))

        pages: list[str] = []

        for page in reader.pages:
            text = page.extract_text()

            if text:
                pages.append(text)

        return "\n\n".join(pages)

    return await to_thread.run_sync(extract)


def extract_pdf(data: bytes) -> ExtractedDocument:
    reader = PdfReader(BytesIO(data))

    pages: list[ExtractedPage] = []

    for index, page in enumerate(reader.pages):
        text = page.extract_text() or ""

        cleaned_text = text.strip()

        if not cleaned_text:
            continue

        pages.append(
            ExtractedPage(
                page_number=index + 1,
                text=cleaned_text,
            )
        )

    return ExtractedDocument(
        pages=pages,
    )


def extract_text_file(data: bytes) -> ExtractedDocument:
    text = data.decode(
        "utf-8",
        errors="replace",
    ).strip()

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


def extract_document_text(
    *,
    data: bytes,
    mime_type: str,
) -> ExtractedDocument:
    if mime_type == "application/pdf":
        return extract_pdf(data)

    if mime_type in {
        "text/plain",
        "text/markdown",
    }:
        return extract_text_file(data)

    raise ValueError(f"Unsupported MIME type: {mime_type}")
