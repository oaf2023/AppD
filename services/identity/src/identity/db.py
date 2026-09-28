"""db — motor asíncrono de PostgreSQL y sesión por solicitud."""

from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from identity.config import get_identity_settings

SCHEMA = "identity"


class Base(DeclarativeBase):
    pass


_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        settings = get_identity_settings()
        _engine = create_async_engine(settings.database_url, pool_pre_ping=True, pool_size=5)
    engine = _engine
    if engine is None:  # pragma: no cover — solo alcanzable si otro hilo reinicia el motor
        raise RuntimeError("motor de identity no inicializado")
    return engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    global _session_factory
    if _session_factory is None:
        _session_factory = async_sessionmaker(get_engine(), expire_on_commit=False)
    return _session_factory


async def get_session() -> AsyncIterator[AsyncSession]:
    async with get_session_factory()() as session:
        yield session


def reset_engine() -> None:
    """Solo para tests: fuerza la recreación del motor con otra URL."""
    global _engine, _session_factory
    _engine = None
    _session_factory = None


__all__ = ["SCHEMA", "Base", "get_engine", "get_session", "get_session_factory", "reset_engine"]
