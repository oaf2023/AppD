"""Pruebas unitarias de rate limit e idempotencia (ADR-0010)."""

from __future__ import annotations

import pytest
from platform_kernel.errors import ConflictError, RateLimitedError
from platform_kernel.idempotency import (
    InMemoryIdempotencyStore,
    idempotent_execute,
    request_hash,
)
from platform_kernel.ratelimit import InMemoryRateLimiter, enforce


async def test_ventana_fija_permite_hasta_el_limite() -> None:
    limiter = InMemoryRateLimiter()
    for _ in range(3):
        result = await limiter.hit("k", limit=3, window_seconds=60)
        assert result.allowed
        assert result.remaining >= 0
    with pytest.raises(RateLimitedError):
        await enforce(limiter, "k", limit=3, window_seconds=60)


async def test_enforce_incluye_retry_after() -> None:
    limiter = InMemoryRateLimiter()
    await enforce(limiter, "k", limit=1, window_seconds=60)
    with pytest.raises(RateLimitedError) as exc:
        await enforce(limiter, "k", limit=1, window_seconds=60)
    assert exc.value.extra["retry_after"] >= 1


async def test_idempotencia_ejecuta_una_sola_vez() -> None:
    store = InMemoryIdempotencyStore()
    calls = 0

    async def execute() -> tuple[int, dict[str, str]]:
        nonlocal calls
        calls += 1
        return 201, {"ok": "true"}

    status, body, replayed = await idempotent_execute(
        store=store, scope="t", key="k1", payload={"a": 1}, execute=execute
    )
    assert (status, body, replayed) == (201, {"ok": "true"}, False)

    status, body, replayed = await idempotent_execute(
        store=store, scope="t", key="k1", payload={"a": 1}, execute=execute
    )
    assert (status, body, replayed) == (201, {"ok": "true"}, True)
    assert calls == 1


async def test_idempotencia_cuerpo_distinto_conflicta() -> None:
    store = InMemoryIdempotencyStore()

    async def execute() -> tuple[int, dict[str, str]]:
        return 201, {"ok": "true"}

    await idempotent_execute(store=store, scope="t", key="k2", payload={"a": 1}, execute=execute)
    with pytest.raises(ConflictError, match="cuerpo distinto"):
        await idempotent_execute(store=store, scope="t", key="k2", payload={"a": 2}, execute=execute)


def test_request_hash_canonico_orden_independiente() -> None:
    assert request_hash({"b": 2, "a": 1}) == request_hash({"a": 1, "b": 2})
    assert request_hash({"a": 1}) != request_hash({"a": 2})
