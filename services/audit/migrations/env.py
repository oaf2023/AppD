"""migrations/env.py — entorno Alembic asíncrono del Audit Service."""

from __future__ import annotations

import asyncio
import os

import audit.models  # noqa: F401
from alembic import context
from audit.db import SCHEMA, Base
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

config = context.config
if config.config_file_name is not None and not config.get_main_option("sqlalchemy.url"):
    config.set_main_option("sqlalchemy.url", os.environ.get("DATABASE_URL", ""))

target_metadata = Base.metadata


def do_run_migrations(connection: Connection) -> None:
    if connection.dialect.name == "postgresql":
        connection.exec_driver_sql(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")
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


if context.is_offline_mode():
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        schema=SCHEMA,
    )
    with context.begin_transaction():
        context.run_migrations()
else:
    asyncio.run(run_async_migrations())
