"""ids — generación de identificadores: UUIDv7 (ordenable por tiempo) y correlación."""

from __future__ import annotations

import os
import time
import uuid


def new_uuid7() -> uuid.UUID:
    """UUIDv7 (RFC 9562): 48 bits de timestamp ms + aleatoriedad, ordenable por creación."""
    timestamp_ms = int(time.time() * 1000) & 0xFFFFFFFFFFFF
    raw = bytearray(os.urandom(16))
    raw[0:6] = timestamp_ms.to_bytes(6, "big")
    raw[6] = 0x70 | (raw[6] & 0x0F)  # versión 7 en el nibble alto del byte 6
    raw[8] = 0x80 | (raw[8] & 0x3F)  # variante RFC 4122 (10xx) en el byte 8
    return uuid.UUID(bytes=bytes(raw))


def new_correlation_id() -> str:
    return str(new_uuid7())


def new_request_id() -> str:
    return str(new_uuid7())


def new_opaque_token(nbytes: int = 32) -> str:
    """Token opaco aleatorio de 256 bits por defecto (refresh, verify, reset)."""
    return os.urandom(nbytes).hex()


__all__ = ["new_correlation_id", "new_opaque_token", "new_request_id", "new_uuid7"]
