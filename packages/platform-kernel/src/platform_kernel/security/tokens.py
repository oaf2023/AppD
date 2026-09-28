"""Tokens — JWT de acceso/servicio y hashes de tokens opacos (ADR-0008, ADR-0010)."""

from __future__ import annotations

import hashlib
import time
from typing import Any

import jwt

from platform_kernel.ids import new_opaque_token

ALGORITHM = "HS256"
TOKEN_TYPE_ACCESS = "access"
TOKEN_TYPE_SERVICE = "service"


class TokenError(ValueError):
    """Token inválido, caducado o con tipo incorrecto."""


def encode_jwt(
    claims: dict[str, Any],
    *,
    secret: str,
    issuer: str,
    audience: str,
    ttl_seconds: int,
) -> str:
    now = int(time.time())
    payload = {
        **claims,
        "iat": now,
        "nbf": now,
        "exp": now + ttl_seconds,
        "iss": issuer,
        "aud": audience,
    }
    return jwt.encode(payload, secret, algorithm=ALGORITHM)


def decode_jwt(
    token: str,
    *,
    secret: str,
    issuer: str,
    audience: str,
    expected_type: str,
    leeway_seconds: int = 5,
) -> dict[str, Any]:
    try:
        payload = jwt.decode(
            token,
            secret,
            algorithms=[ALGORITHM],
            issuer=issuer,
            audience=audience,
            leeway=leeway_seconds,
            options={"require": ["exp", "iat", "iss", "aud", "typ"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise TokenError("token caducado") from exc
    except jwt.InvalidTokenError as exc:
        raise TokenError("token inválido") from exc
    if payload.get("typ") != expected_type:
        raise TokenError("tipo de token incorrecto")
    return payload


def hash_opaque_token(token: str) -> str:
    """SHA-256 del token opaco: en BD solo se guarda el hash (nunca el token)."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def new_access_token(
    *,
    user_id: str,
    session_id: str,
    roles: list[str],
    secret: str,
    issuer: str,
    audience: str,
    ttl_seconds: int,
) -> str:
    return encode_jwt(
        {
            "typ": TOKEN_TYPE_ACCESS,
            "sub": user_id,
            "sid": session_id,
            "roles": roles,
            "jti": new_opaque_token(16),
        },
        secret=secret,
        issuer=issuer,
        audience=audience,
        ttl_seconds=ttl_seconds,
    )


def new_service_token(
    *,
    service_name: str,
    secret: str,
    issuer: str,
    audience: str,
    ttl_seconds: int = 300,
) -> str:
    return encode_jwt(
        {"typ": TOKEN_TYPE_SERVICE, "sub": service_name, "jti": new_opaque_token(16)},
        secret=secret,
        issuer=issuer,
        audience=audience,
        ttl_seconds=ttl_seconds,
    )


__all__ = [
    "ALGORITHM",
    "TOKEN_TYPE_ACCESS",
    "TOKEN_TYPE_SERVICE",
    "TokenError",
    "decode_jwt",
    "encode_jwt",
    "hash_opaque_token",
    "new_access_token",
    "new_service_token",
]
