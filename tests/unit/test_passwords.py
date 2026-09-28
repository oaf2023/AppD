"""Pruebas unitarias de contraseñas Argon2id (ADR-0008)."""

from __future__ import annotations

import pytest
from platform_kernel.security.passwords import (
    MIN_PASSWORD_LENGTH,
    PasswordPolicyError,
    hash_password,
    needs_rehash,
    validate_password_policy,
    verify_password,
)


def test_hash_y_verificacion_correctos() -> None:
    password = "Str0ng!Passw0rd-2026"
    stored = hash_password(password)
    assert stored != password
    assert stored.startswith("$argon2id$")
    assert verify_password(stored, password) is True


def test_password_incorrecta_falla() -> None:
    stored = hash_password("Str0ng!Passw0rd-2026")
    assert verify_password(stored, "Otra!Passw0rd-2026") is False


def test_hash_invalido_falla_sin_excepcion() -> None:
    assert verify_password("no-es-un-hash", "Str0ng!Passw0rd-2026") is False


def test_política_longitud_minima() -> None:
    with pytest.raises(PasswordPolicyError, match=f"al menos {MIN_PASSWORD_LENGTH}"):
        validate_password_policy("corto")


def test_política_contraseña_común() -> None:
    with pytest.raises(PasswordPolicyError, match="demasiado común"):
        validate_password_policy("password1234")


def test_needs_rehash_en_hash_normal() -> None:
    assert needs_rehash(hash_password("Str0ng!Passw0rd-2026")) is False
    assert needs_rehash("garbage") is True
