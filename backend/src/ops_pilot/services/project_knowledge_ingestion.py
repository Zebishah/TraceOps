import logging
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from langchain_text_splitters import RecursiveCharacterTextSplitter
from qdrant_client import models
from sqlalchemy import text

from ops_pilot.ai.embeddings import embed_texts
from ops_pilot.core.config import get_settings
from ops_pilot.db.engine import engine
from ops_pilot.schemas.project_knowledge_ingestion import (
    ProjectKnowledgeChunk,
)
from ops_pilot.vectorstore.qdrant import (
    get_qdrant_client,
)

logger = logging.getLogger(__name__)
PROJECT_KNOWLEDGE_NAMESPACE = uuid.UUID("6c8242f0-8126-4e26-9187-78d26c65bbba")

CHUNK_SIZE = 1000
CHUNK_OVERLAP = 150


# Stable, application-specific PostgreSQL advisory-lock key.
# All TraceOps knowledge rebuild workers must use this key.
PROJECT_KNOWLEDGE_REBUILD_LOCK_KEY = 684271950137


@asynccontextmanager
async def acquire_project_knowledge_rebuild_lock() -> AsyncIterator[None]:
    """Allow only one project-knowledge rebuild at a time.

    The PostgreSQL transaction keeps the advisory lock held
    for the duration of the rebuild.
    """
    async with engine.connect() as connection:
        async with connection.begin():
            acquired = await connection.scalar(
                text("SELECT pg_try_advisory_xact_lock(:lock_key)"),
                {
                    "lock_key": PROJECT_KNOWLEDGE_REBUILD_LOCK_KEY,
                },
            )

            if acquired is not True:
                raise RuntimeError("Another project knowledge rebuild is already running")

            yield

            # Detect a broken lock connection before
            # considering this rebuild successful.
            await connection.execute(text("SELECT 1"))


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


async def _index_project_knowledge_directory_unlocked(
    *,
    directory: Path,
) -> int:
    """Build a new Qdrant collection, verify it, then publish.

    Never destroy the currently active collection before the
    replacement has been fully uploaded and verified.
    """
    markdown_files = sorted(directory.glob("*.md"))

    if not markdown_files:
        raise RuntimeError(f"No markdown files found in {directory}")

    all_chunks: list[ProjectKnowledgeChunk] = []

    for path in markdown_files:
        text = path.read_text(encoding="utf-8")

        all_chunks.extend(
            create_project_knowledge_chunks(
                source=path.name,
                text=text,
            )
        )

    if not all_chunks:
        raise RuntimeError("Project knowledge produced no chunks")

    vectors = await embed_texts([chunk.text for chunk in all_chunks])

    if len(vectors) != len(all_chunks):
        raise RuntimeError("Project knowledge embedding count does not match chunk count")

    settings = get_settings()
    client = get_qdrant_client()

    legacy_name = settings.qdrant_project_knowledge_collection_name

    active_alias = f"{legacy_name}__active"
    version_name = f"{legacy_name}__v_{uuid.uuid4().hex}"

    # The existing collection is NOT modified or deleted.
    await client.create_collection(
        collection_name=version_name,
        vectors_config=models.VectorParams(
            size=settings.embedding_dimension,
            distance=models.Distance.COSINE,
        ),
    )

    # This collection exists only as a replacement candidate
    # until the final alias operation succeeds.
    try:
        for field_name in ("source", "section"):
            await client.create_payload_index(
                collection_name=version_name,
                field_name=field_name,
                field_schema=models.PayloadSchemaType.KEYWORD,
                wait=True,
            )

        points = [
            models.PointStruct(
                id=str(chunk.id),
                vector=vector,
                payload={
                    "source": chunk.source,
                    "section": chunk.section,
                    "chunk_index": chunk.chunk_index,
                    "text": chunk.text,
                    "embedding_model": settings.embedding_model,
                },
            )
            for chunk, vector in zip(
                all_chunks,
                vectors,
                strict=True,
            )
        ]

        # Upload in bounded chunks instead of submitting one
        # potentially enormous request.
        batch_size = 100

        for start in range(0, len(points), batch_size):
            await client.upsert(
                collection_name=version_name,
                points=points[start : start + batch_size],
                wait=True,
            )

        # Never promote a partially indexed collection.
        count_result = await client.count(
            collection_name=version_name,
            exact=True,
        )

        if count_result.count != len(points):
            raise RuntimeError(
                "Project knowledge verification failed: "
                f"expected {len(points)} points, "
                f"found {count_result.count}"
            )

        # Alias updates are applied atomically by Qdrant.
        # The old collection itself is never deleted.
        aliases = await client.get_aliases()

        alias_exists = any(alias.alias_name == active_alias for alias in aliases.aliases)

        operations: list[models.AliasOperations] = []

        if alias_exists:
            operations.append(
                models.DeleteAliasOperation(
                    delete_alias=models.DeleteAlias(
                        alias_name=active_alias,
                    )
                )
            )

        operations.append(
            models.CreateAliasOperation(
                create_alias=models.CreateAlias(
                    collection_name=version_name,
                    alias_name=active_alias,
                )
            )
        )

        try:
            await client.update_collection_aliases(
                change_aliases_operations=operations,
            )
        except Exception:
            # The request may have succeeded even though its
            # response was lost. Inspect the authoritative alias.
            logger.exception(
                "project_knowledge_alias_publication_uncertain",
                extra={
                    "alias": active_alias,
                    "candidate_collection": version_name,
                },
            )

        # Do not delete or republish automatically.
        # The following existing alias verification will
        # determine whether publication is observable.

        # Verify the alias resolves to the new collection.
        published_aliases = await client.get_aliases()

        published = any(
            alias.alias_name == active_alias and alias.collection_name == version_name
            for alias in published_aliases.aliases
        )

        if not published:
            raise RuntimeError("Project knowledge alias publication could not be verified")

        return len(points)

    except Exception:
        # Do not delete the candidate here: if the alias
        # operation succeeded but its response was lost,
        # deleting the candidate could destroy live data.
        #
        # Orphaned candidates must be cleaned up separately,
        # after verifying they are not referenced by an alias.
        raise


async def index_project_knowledge_directory(
    *,
    directory: Path,
) -> int:
    """Serialize knowledge rebuilds across application workers."""
    async with acquire_project_knowledge_rebuild_lock():
        return await _index_project_knowledge_directory_unlocked(
            directory=directory,
        )
