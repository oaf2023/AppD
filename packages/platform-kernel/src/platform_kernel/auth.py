"""auth — dependencias FastAPI de autorización (usuario y servicio)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Annotated

from fastapi import Depends, Request

from platform_kernel.config import KernelSettings, get_settings
from platform_kernel.context import bind_context
from platform_kernel.errors import ForbiddenError, UnauthorizedError
from platform_kernel.security.tokens import (
    TOKEN_TYPE_ACCESS,
    TOKEN_TYPE_SERVICE,
    TokenError,
    decode_jwt,
)


@dataclass(frozen=True)
class AuthContext:
    user_id: str
    session_id: str
    roles: tuple[str, ...] = field(default_factory=tuple)


def _bearer(request: Request) -> str:
    header = request.headers.get("authorization", "")
    if not header.lower().startswith("bearer "):
        raise UnauthorizedError("Cabecera Authorization ausente o inválida")
    return header[7:].strip()


def require_user(request: Request) -> AuthContext:
    settings = get_settings()
    token = _bearer(request)
    try:
        claims = decode_jwt(
            token,
            secret=settings.jwt_secret,
            issuer=settings.jwt_issuer,
            audience=settings.jwt_audience,
            expected_type=TOKEN_TYPE_ACCESS,
        )
    except TokenError as exc:
        raise UnauthorizedError(str(exc)) from exc
    ctx = AuthContext(
        user_id=str(claims["sub"]),
        session_id=str(claims.get("sid", "")),
        roles=tuple(claims.get("roles") or ()),
    )
    request.state.auth = ctx
    bind_context(user_id=ctx.user_id, session_id=ctx.session_id, roles=ctx.roles)
    return ctx


def require_roles(*roles: str) -> Callable[..., AuthContext]:
    allowed = set(roles)

    def dependency(auth: Annotated[AuthContext, Depends(require_user)]) -> AuthContext:
        if not allowed.intersection(auth.roles):
            raise ForbiddenError(f"Requiere uno de los roles: {', '.join(sorted(allowed))}")
        return auth

    return dependency


def decode_claims_optional(request: Request) -> AuthContext | None:
    """Decodifica el JWT si existe y es válido; devuelve None en caso contrario."""
    header = request.headers.get("authorization", "")
    if not header.lower().startswith("bearer "):
        return None
    settings = get_settings()
    try:
        claims = decode_jwt(
            header[7:].strip(),
            secret=settings.jwt_secret,
            issuer=settings.jwt_issuer,
            audience=settings.jwt_audience,
            expected_type=TOKEN_TYPE_ACCESS,
        )
    except TokenError:
        return None
    return AuthContext(
        user_id=str(claims["sub"]),
        session_id=str(claims.get("sid", "")),
        roles=tuple(claims.get("roles") or ()),
    )


def require_service(request: Request) -> str:
    """Valida el token de servicio para endpoints internos (ADR-0017)."""
    settings: KernelSettings = get_settings()
    token = _bearer(request)
    try:
        claims = decode_jwt(
            token,
            secret=settings.service_token_secret,
            issuer=settings.jwt_issuer,
            audience=settings.service_token_audience,
            expected_type=TOKEN_TYPE_SERVICE,
        )
    except TokenError as exc:
        raise UnauthorizedError("Token de servicio inválido") from exc
    return str(claims["sub"])


__all__ = ["AuthContext", "require_roles", "require_service", "require_user"]
