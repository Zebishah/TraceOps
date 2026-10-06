import asyncio
from collections.abc import MutableMapping
from logging.config import fileConfig
from typing import Literal

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

import ops_pilot.models  # noqa: F401
from ops_pilot.core.config import get_settings
from ops_pilot.db.base import Base

type AlembicObjectType = Literal[
    "schema",
    "table",
    "column",
    "index",
    "unique_constraint",
    "foreign_key_constraint",
    "check_constraint",
]

type AlembicParentName = Literal[
    "schema_name",
    "table_name",
    "schema_qualified_table_name",
]


LANGGRAPH_CHECKPOINT_TABLES = {
    "checkpoint_blobs",
    "checkpoint_migrations",
    "checkpoint_writes",
    "checkpoints",
}


config = context.config

settings = get_settings()

config.set_main_option(
    "sqlalchemy.url",
    settings.database_url.replace(
        "%",
        "%%",
    ),
)

if config.config_file_name is not None:
    fileConfig(
        config.config_file_name,
    )

target_metadata = Base.metadata


def include_name(
    name: str | None,
    type_: AlembicObjectType,
    parent_names: MutableMapping[
        AlembicParentName,
        str | None,
    ],
) -> bool:
    # Required by Alembic callback signature.
    # We do not need parent_names for this filter.
    del parent_names

    if type_ == "table" and name in LANGGRAPH_CHECKPOINT_TABLES:
        return False

    return True


def run_migrations_offline() -> None:
    url = config.get_main_option(
        "sqlalchemy.url",
    )

    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={
            "paramstyle": "named",
        },
        include_name=include_name,
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(
    connection: Connection,
) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        include_name=include_name,
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(
            config.config_ini_section,
            {},
        ),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(
            do_run_migrations,
        )

    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
