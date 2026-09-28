"""idempotencia — patrón Idempotency-Key + hash de solicitud + respuesta almacenada.

Cobertura obligatoria (ADR-0010): orders, payments, withdrawals, deposits,
webhooks, ledger postings. En Fase 1 se aplica al registro de usuario y queda
la primitiva lista para los flujos financieros de la Fase 2+.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Generic, Protocol, TypeVar

from platform_kernel.errors import ConflictError

T = TypeVar("T")

DEFAULT_TTL_SECONDS = 24 * 60 * 60


def request_hash(payload: Any) -> str:
    """SHA-256 canónico del cuerpo de la solicitud."""
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass
class StoredResponse(Generic[T]):
    request_hash: str
    status_code: int
    body: T
    created_at: float


class IdempotencyStore(Protocol):  # type: ignore[misc]
    async def get(self, scope: str, key: str) -> StoredResponse[Any] | None: ...

    async def put(self, scope: str, key: str, value: StoredResponse[Any], ttl_seconds: int) -> None: ...


class InMemoryIdempotencyStore:
    def __init__(self) -> None:
        self._data: dict[str, StoredResponse[Any]] = {}

    @staticmethod
    def _full(scope: str, key: str) -> str:
        return f"{scope}:{key}"

    async def get(self, scope: str, key: str) -> StoredResponse[Any] | None:
        return self._data.get(self._full(scope, key))

    async def put(self, scope: str, key: str, value: StoredResponse[Any], ttl_seconds: int) -> None:
        self._data[self._full(scope, key)] = value


class RedisIdempotencyStore:
    def __init__(self, redis_client: Any) -> None:
        self._redis = redis_client

    async def get(self, scope: str, key: str) -> StoredResponse[Any] | None:
        raw = await self._redis.get(f"idem:{scope}:{key}")
        if not raw:
            return None
        data = json.loads(raw)
        return StoredResponse(
            request_hash=data["request_hash"],
            status_code=data["status_code"],
            body=data["body"],
            created_at=data["created_at"],
        )

    async def put(self, scope: str, key: str, value: StoredResponse[Any], ttl_seconds: int) -> None:
        payload = json.dumps(
            {
                "request_hash": value.request_hash,
                "status_code": value.status_code,
                "body": value.body,
                "created_at": value.created_at,
            },
            default=str,
        )
        await self._redis.set(f"idem:{scope}:{key}", payload, ex=ttl_seconds)


async def idempotent_execute(
    *,
    store: IdempotencyStore,
    scope: str,
    key: str,
    payload: Any,
    execute: Callable[[], Awaitable[tuple[int, T]]],
    ttl_seconds: int = DEFAULT_TTL_SECONDS,
) -> tuple[int, T, bool]:
    """Ejecuta `execute` una sola vez por (scope, key).

    Devuelve (status_code, body, replayed). Si la clave ya existe con otro
    hash de solicitud → 409 Conflict (uso incorrecto de la clave).
    """
    h = request_hash(payload)
    existing = await store.get(scope, key)
    if existing is not None:
        if existing.request_hash != h:
            raise ConflictError("Idempotency-Key reutilizada con un cuerpo distinto")
        return existing.status_code, existing.body, True

    status, body = await execute()
    import time as _time

    await store.put(scope, key, StoredResponse(h, status, body, _time.time()), ttl_seconds)
    return status, body, False


async def build_idempotency_store(redis_url: str | None) -> IdempotencyStore:
    if not redis_url:
        return InMemoryIdempotencyStore()
    import redis.asyncio as aioredis

    return RedisIdempotencyStore(aioredis.from_url(redis_url, decode_responses=True))


__all__ = [
    "DEFAULT_TTL_SECONDS",
    "IdempotencyStore",
    "InMemoryIdempotencyStore",
    "RedisIdempotencyStore",
    "StoredResponse",
    "build_idempotency_store",
    "idempotent_execute",
    "request_hash",
]
