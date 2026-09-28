"""Passwords con Argon2id (ADR-0008). Nunca texto plano, nunca hash débil."""

from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

_hasher = PasswordHasher(time_cost=3, memory_cost=64 * 1024, parallelism=4, hash_len=32, salt_len=16)

MIN_PASSWORD_LENGTH = 12
MAX_PASSWORD_LENGTH = 256


class PasswordPolicyError(ValueError):
    pass


def validate_password_policy(password: str) -> None:
    """Política mínima: longitud ≥12 y sin secuencias obvias. Ampliable (ver S-mvp-scope)."""
    if len(password) < MIN_PASSWORD_LENGTH:
        raise PasswordPolicyError(f"la contraseña debe tener al menos {MIN_PASSWORD_LENGTH} caracteres")
    if len(password) > MAX_PASSWORD_LENGTH:
        raise PasswordPolicyError(f"la contraseña no puede exceder {MAX_PASSWORD_LENGTH} caracteres")
    if password.lower() in {"password1234", "123456789012", "qwertyuiop12"}:
        raise PasswordPolicyError("contraseña demasiado común")


def hash_password(password: str) -> str:
    validate_password_policy(password)
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(password_hash: str) -> bool:
    try:
        return _hasher.check_needs_rehash(password_hash)
    except InvalidHashError:
        return True


__all__ = [
    "MAX_PASSWORD_LENGTH",
    "MIN_PASSWORD_LENGTH",
    "PasswordPolicyError",
    "hash_password",
    "needs_rehash",
    "validate_password_policy",
    "verify_password",
]
