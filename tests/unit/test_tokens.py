"""Pruebas unitarias de tokens JWT (ADR-0008)."""

from __future__ import annotations

import time

import pytest
from platform_kernel.security.tokens import (
    TOKEN_TYPE_ACCESS,
    TokenError,
    decode_jwt,
    encode_jwt,
    hash_opaque_token,
    new_access_token,
    new_service_token,
)

SECRET = "unit-test-secret-0123456789abcdef0123456789abcdef"
ISSUER = "platform-identity"
AUDIENCE = "platform-api"


def _encode(**extra: object) -> str:
    return encode_jwt(
        {"typ": TOKEN_TYPE_ACCESS, "sub": "u1", "sid": "s1", "roles": ["user"], **extra},
        secret=SECRET,
        issuer=ISSUER,
        audience=AUDIENCE,
        ttl_seconds=900,
    )


def test_roundtrip_access_token() -> None:
    token = _encode()
    claims = decode_jwt(token, secret=SECRET, issuer=ISSUER, audience=AUDIENCE, expected_type="access")
    assert claims["sub"] == "u1"
    assert claims["sid"] == "s1"
    assert claims["roles"] == ["user"]


def test_token_caducado_rechazado() -> None:
    token = encode_jwt(
        {"typ": "access", "sub": "u1"},
        secret=SECRET,
        issuer=ISSUER,
        audience=AUDIENCE,
        ttl_seconds=-10,
    )
    time.sleep(0.1)
    with pytest.raises(TokenError, match="caducado"):
        decode_jwt(token, secret=SECRET, issuer=ISSUER, audience=AUDIENCE, expected_type="access")


def test_tipo_incorrecto_rechazado() -> None:
    token = new_service_token(service_name="identity", secret=SECRET, issuer=ISSUER, audience=AUDIENCE)
    with pytest.raises(TokenError, match="tipo de token incorrecto"):
        decode_jwt(token, secret=SECRET, issuer=ISSUER, audience=AUDIENCE, expected_type="access")


def test_secret_incorrecto_rechazado() -> None:
    token = _encode()
    with pytest.raises(TokenError, match="token inválido"):
        decode_jwt(
            token,
            secret="otro-secret-distinto-0123456789abcdef",
            issuer=ISSUER,
            audience=AUDIENCE,
            expected_type="access",
        )


def test_audience_incorrecta_rechazada() -> None:
    token = _encode()
    with pytest.raises(TokenError, match="token inválido"):
        decode_jwt(
            token,
            secret=SECRET,
            issuer=ISSUER,
            audience="otra-audience",
            expected_type="access",
        )


def test_access_token_ttl_acotado_a_15_min() -> None:
    token = new_access_token(
        user_id="u1",
        session_id="s1",
        roles=["user"],
        secret=SECRET,
        issuer=ISSUER,
        audience=AUDIENCE,
        ttl_seconds=900,
    )
    claims = decode_jwt(token, secret=SECRET, issuer=ISSUER, audience=AUDIENCE, expected_type="access")
    assert claims["exp"] - claims["iat"] == 900


def test_service_token_ttl_5_min() -> None:
    token = new_service_token(service_name="identity", secret=SECRET, issuer=ISSUER, audience=AUDIENCE)
    claims = decode_jwt(token, secret=SECRET, issuer=ISSUER, audience=AUDIENCE, expected_type="service")
    assert claims["exp"] - claims["iat"] == 300


def test_hash_opaque_es_sha256_y_determinista() -> None:
    token = "token-opaco-de-ejemplo-1234567890"
    h1, h2 = hash_opaque_token(token), hash_opaque_token(token)
    assert h1 == h2
    assert len(h1) == 64
    assert token not in h1
