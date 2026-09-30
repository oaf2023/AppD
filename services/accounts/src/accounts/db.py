"""db - motor asíncrono y sesión del Accounts Service."""

from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from accounts.config import get_accounts_settings

SCHEMA = "accounts"

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


class Base(DeclarativeBase):
    pass


def get_engine() -> AsyncEngine:
    global _engine
    if _engine is None:
        settings = get_accounts_settings()
        _engine = create_async_engine(settings.accounts_database_url, pool_pre_ping=True, pool_size=5)
    engine = _engine
    if engine is None:  # pragma: no cover - solo alcanzable si otro hilo reinicia el motor
        raise RuntimeError("motor de accounts no inicializado")
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
    global _engine, _session_factory
    _engine = None
    _session_factory = None


__all__ = ["SCHEMA", "Base", "get_engine", "get_session", "get_session_factory", "reset_engine"]
