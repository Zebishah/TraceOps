import asyncio
from pathlib import Path

from ops_pilot.services.project_knowledge_ingestion import (
    index_project_knowledge_directory,
)


async def main() -> None:
    project_root = Path(__file__).resolve().parents[2]

    knowledge_directory = project_root / "docs" / "project-knowledge"

    indexed_count = await index_project_knowledge_directory(
        directory=knowledge_directory,
    )

    print(f"Indexed {indexed_count} project knowledge chunks.")


if __name__ == "__main__":
    asyncio.run(main())
