import uuid
from pathlib import Path

from langchain_text_splitters import RecursiveCharacterTextSplitter
from qdrant_client import models

from ops_pilot.ai.embeddings import embed_texts
from ops_pilot.core.config import get_settings
from ops_pilot.schemas.project_knowledge_ingestion import (
    ProjectKnowledgeChunk,
)
from ops_pilot.vectorstore.qdrant import (
    ensure_project_knowledge_collection,
    get_qdrant_client,
)

PROJECT_KNOWLEDGE_NAMESPACE = uuid.UUID("6c8242f0-8126-4e26-9187-78d26c65bbba")

CHUNK_SIZE = 1000
CHUNK_OVERLAP = 150


def extract_markdown_sections(
    *,
    source: str,
    text: str,
) -> list[tuple[str, str]]:
    sections: list[tuple[str, str]] = []

    current_section = "Overview"
    current_lines: list[str] = []

    for line in text.splitlines():
        stripped = line.strip()

        if stripped.startswith("#"):
            if current_lines:
                section_text = "\n".join(
                    current_lines,
                ).strip()

                if section_text:
                    sections.append(
                        (
                            current_section,
                            section_text,
                        )
                    )

            current_section = stripped.lstrip("#").strip()
            current_lines = []
            continue

        current_lines.append(line)

    if current_lines:
        section_text = "\n".join(
            current_lines,
        ).strip()

        if section_text:
            sections.append(
                (
                    current_section,
                    section_text,
                )
            )

    if not sections and text.strip():
        sections.append(
            (
                source,
                text.strip(),
            )
        )

    return sections


def create_project_knowledge_chunks(
    *,
    source: str,
    text: str,
) -> list[ProjectKnowledgeChunk]:
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

    sections = extract_markdown_sections(
        source=source,
        text=text,
    )

    chunks: list[ProjectKnowledgeChunk] = []

    chunk_index = 0

    for section, section_text in sections:
        pieces = splitter.split_text(
            section_text,
        )

        for piece in pieces:
            cleaned_text = piece.strip()

            if not cleaned_text:
                continue

            chunk_id = uuid.uuid5(
                PROJECT_KNOWLEDGE_NAMESPACE,
                f"{source}:{section}:{chunk_index}",
            )

            chunks.append(
                ProjectKnowledgeChunk(
                    id=chunk_id,
                    source=source,
                    section=section,
                    chunk_index=chunk_index,
                    text=cleaned_text,
                )
            )

            chunk_index += 1

    return chunks


async def index_project_knowledge_directory(
    *,
    directory: Path,
) -> int:
    await ensure_project_knowledge_collection()

    markdown_files = sorted(
        directory.glob("*.md"),
    )

    if not markdown_files:
        raise RuntimeError(
            f"No markdown files found in {directory}",
        )

    all_chunks: list[ProjectKnowledgeChunk] = []

    for path in markdown_files:
        text = path.read_text(
            encoding="utf-8",
        )

        chunks = create_project_knowledge_chunks(
            source=path.name,
            text=text,
        )

        all_chunks.extend(
            chunks,
        )

    if not all_chunks:
        raise RuntimeError(
            "Project knowledge produced no chunks",
        )

    vectors = await embed_texts([chunk.text for chunk in all_chunks])

    if len(vectors) != len(all_chunks):
        raise RuntimeError("Project knowledge embedding count does not match chunk count")

    settings = get_settings()
    client = get_qdrant_client()

    points: list[models.PointStruct] = []

    for chunk, vector in zip(
        all_chunks,
        vectors,
        strict=True,
    ):
        points.append(
            models.PointStruct(
                id=str(chunk.id),
                vector=vector,
                payload={
                    "source": chunk.source,
                    "section": chunk.section,
                    "chunk_index": chunk.chunk_index,
                    "text": chunk.text,
                    "embedding_model": (settings.embedding_model),
                },
            )
        )

    await client.upsert(
        collection_name=(settings.qdrant_project_knowledge_collection_name),
        points=points,
        wait=True,
    )

    return len(points)
