"""migrations/env.py — entorno Alembic asíncrono del Identity Service."""

from __future__ import annotations

import asyncio
import os

import identity.models  # noqa: F401 — registra los modelos en Base.metadata
from alembic import context
from identity.db import SCHEMA, Base
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

config = context.config
if config.config_file_name is not None and not config.get_main_option("sqlalchemy.url"):
    config.set_main_option("sqlalchemy.url", os.environ.get("DATABASE_URL", ""))

target_metadata = Base.metadata


def _ensure_schema(connection: Connection) -> None:
    if connection.dialect.name == "postgresql":
        connection.exec_driver_sql(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        schema=SCHEMA,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    _ensure_schema(connection)
    context.configure(connection=connection, target_metadata=target_metadata, schema=SCHEMA)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
        await connection.commit()
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
