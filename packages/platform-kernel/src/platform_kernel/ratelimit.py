"""ratelimit — límite de velocidad por clave (IP, usuario, ruta).

Ventana fija por intervalo temporal. Redis cuando hay `redis_url`; memoria en
local/test. Clasificación: PARCIAL (la ventana fija es una aproximación
aceptable para Fase 1; se puede sustituir por ventana deslizante sin cambiar
la interfaz).
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Protocol

from platform_kernel.errors import RateLimitedError


@dataclass(frozen=True)
class RateLimitResult:
    allowed: bool
    remaining: int
    limit: int
    retry_after: int


class RateLimiter(Protocol):
    async def hit(self, key: str, limit: int, window_seconds: int, cost: int = 1) -> RateLimitResult: ...

    async def reset(self, key: str) -> None: ...


class InMemoryRateLimiter:
    """Ventana fija en memoria. Proceso único; no sirve entre réplicas."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._buckets: dict[str, tuple[int, int]] = {}

    def _window(self, window_seconds: int) -> int:
        return int(self._clock() // window_seconds)

    async def hit(self, key: str, limit: int, window_seconds: int, cost: int = 1) -> RateLimitResult:
        window = self._window(window_seconds)
        current_window, count = self._buckets.get(key, (window, 0))
        if current_window != window:
            count = 0
        if count + cost > limit:
            elapsed = self._clock() - window * window_seconds
            retry_after = max(1, int(window_seconds - elapsed) + 1)
            self._buckets[key] = (window, count)
            return RateLimitResult(False, max(0, limit - count), limit, retry_after)
        count += cost
        self._buckets[key] = (window, count)
        return RateLimitResult(True, max(0, limit - count), limit, 0)

    async def reset(self, key: str) -> None:
        self._buckets.pop(key, None)


class RedisRateLimiter:
    """Ventana fija en Redis: INCR + EXPIRE por clave de ventana."""

    def __init__(self, redis_client: Any) -> None:
        self._redis = redis_client

    async def hit(self, key: str, limit: int, window_seconds: int, cost: int = 1) -> RateLimitResult:
        window = int(time.time()) // window_seconds
        rkey = f"rl:{key}:{window}"
        count = await self._redis.incrby(rkey, cost)
        if count == cost:
            await self._redis.expire(rkey, window_seconds + 1)
        if count > limit:
            elapsed = int(time.time()) - window * window_seconds
            retry_after = max(1, window_seconds - elapsed + 1)
            return RateLimitResult(False, 0, limit, retry_after)
        return RateLimitResult(True, max(0, limit - count), limit, 0)

    async def reset(self, key: str) -> None:
        window = int(time.time())
        # elimina la ventana actual (clave más reciente plausible)
        await self._redis.delete(f"rl:{key}:{window}")


async def enforce(limiter: RateLimiter, key: str, limit: int, window_seconds: int, cost: int = 1) -> RateLimitResult:
    result = await limiter.hit(key, limit, window_seconds, cost)
    if not result.allowed:
        raise RateLimitedError(result.retry_after)
    return result


async def build_rate_limiter(redis_url: str | None) -> RateLimiter:
    if not redis_url:
        return InMemoryRateLimiter()
    import redis.asyncio as aioredis

    client = aioredis.from_url(redis_url, decode_responses=True)
    return RedisRateLimiter(client)


__all__ = [
    "InMemoryRateLimiter",
    "RateLimitResult",
    "RateLimiter",
    "RedisRateLimiter",
    "build_rate_limiter",
    "enforce",
]
