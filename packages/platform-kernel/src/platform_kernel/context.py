"""context — variables de contexto de trazabilidad (request_id, correlation_id, actor)."""

from __future__ import annotations

import contextvars
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field

from platform_kernel.ids import new_correlation_id

_request_id: contextvars.ContextVar[str | None] = contextvars.ContextVar("request_id", default=None)
_correlation_id: contextvars.ContextVar[str | None] = contextvars.ContextVar("correlation_id", default=None)
_user_id: contextvars.ContextVar[str | None] = contextvars.ContextVar("user_id", default=None)
_session_id: contextvars.ContextVar[str | None] = contextvars.ContextVar("session_id", default=None)
_roles: contextvars.ContextVar[tuple[str, ...]] = contextvars.ContextVar("roles", default=())


@dataclass(frozen=True)
class RequestContext:
    request_id: str | None = None
    correlation_id: str | None = None
    user_id: str | None = None
    session_id: str | None = None
    roles: tuple[str, ...] = field(default_factory=tuple)


def get_request_id() -> str | None:
    return _request_id.get()


def get_correlation_id() -> str | None:
    return _correlation_id.get()


def get_user_id() -> str | None:
    return _user_id.get()


def get_session_id() -> str | None:
    return _session_id.get()


def get_roles() -> tuple[str, ...]:
    return _roles.get()


def get_context() -> RequestContext:
    return RequestContext(
        request_id=get_request_id(),
        correlation_id=get_correlation_id(),
        user_id=get_user_id(),
        session_id=get_session_id(),
        roles=get_roles(),
    )


@contextmanager
def bind_context(
    *,
    request_id: str | None = None,
    correlation_id: str | None = None,
    user_id: str | None = None,
    session_id: str | None = None,
    roles: tuple[str, ...] | None = None,
) -> Iterator[RequestContext]:
    tokens: list[tuple[contextvars.ContextVar[object], object]] = []
    if request_id is not None:
        tokens.append((_request_id, _request_id.set(request_id)))  # type: ignore[arg-type]
    if correlation_id is not None:
        tokens.append((_correlation_id, _correlation_id.set(correlation_id)))  # type: ignore[arg-type]
    if user_id is not None:
        tokens.append((_user_id, _user_id.set(user_id)))  # type: ignore[arg-type]
    if session_id is not None:
        tokens.append((_session_id, _session_id.set(session_id)))  # type: ignore[arg-type]
    if roles is not None:
        tokens.append((_roles, _roles.set(roles)))  # type: ignore[arg-type]
    try:
        yield get_context()
    finally:
        for var, tok in reversed(tokens):
            var.reset(tok)  # type: ignore[arg-type]


def ensure_correlation_id(value: str | None) -> str:
    return value if value else new_correlation_id()


__all__ = [
    "RequestContext",
    "bind_context",
    "ensure_correlation_id",
    "get_context",
    "get_correlation_id",
    "get_request_id",
    "get_roles",
    "get_session_id",
    "get_user_id",
]
