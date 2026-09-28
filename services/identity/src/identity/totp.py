"""totp — TOTP RFC 6238 implementado localmente (sin dependencias externas)."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
import time
import urllib.parse


def generate_secret(length: int = 20) -> str:
    return base64.b32encode(secrets.token_bytes(length)).decode("ascii").rstrip("=")


def _dynamic_truncate(digest: bytes, digits: int) -> str:
    offset = digest[-1] & 0x0F
    code = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return str(code % (10**digits)).zfill(digits)


def hotp(secret: str, counter: int, digits: int = 6) -> str:
    key = base64.b32decode(secret + "=" * (-len(secret) % 8), casefold=True)
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    return _dynamic_truncate(digest, digits)


def totp(secret: str, *, period: int = 30, digits: int = 6, at: float | None = None, offset: int = 0) -> str:
    timestamp = time.time() if at is None else at
    counter = int(timestamp // period) + offset
    return hotp(secret, counter, digits)


def verify_totp(secret: str, code: str, *, period: int = 30, window: int = 1) -> bool:
    if len(code) not in (6, 8):
        return False
    for offset in range(-window, window + 1):
        if hmac.compare_digest(totp(secret, period=period, offset=offset), code):
            return True
    return False


def otpauth_url(secret: str, account: str, issuer: str) -> str:
    label = urllib.parse.quote(f"{issuer}:{account}")
    query = urllib.parse.urlencode({"secret": secret, "issuer": issuer, "algorithm": "SHA1", "digits": 6, "period": 30})
    return f"otpauth://totp/{label}?{query}"


__all__ = ["generate_secret", "hotp", "otpauth_url", "totp", "verify_totp"]
