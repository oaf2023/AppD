"""pagination — cursor opaco sobre `(ts DESC, id DESC)` (Q-api-map §1.4, BUILD-027).

Sin offset: inmune a inserts concurrentes. Cursor inválido → `422 VALIDATION_ERROR`.
"""

from __future__ import annotations

import base64
import binascii
import uuid
from datetime import datetime

from platform_kernel.errors import ValidationError


def encode_cursor(ts: datetime, row_id: uuid.UUID) -> str:
    raw = f"{ts.isoformat()}|{row_id}".encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        ts_raw, _, row_id = base64.urlsafe_b64decode(padded.encode()).decode().partition("|")
        return datetime.fromisoformat(ts_raw), uuid.UUID(row_id)
    except (ValueError, binascii.Error) as exc:
        raise ValidationError("cursor inválido") from exc


def encode_symbol_cursor(symbol: str) -> str:
    """Cursor opaco sobre el símbolo canónico (keyset `symbol ASC` — Q §1.4)."""
    return base64.urlsafe_b64encode(symbol.encode()).decode().rstrip("=")


def decode_symbol_cursor(cursor: str) -> str:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        symbol = base64.urlsafe_b64decode(padded.encode()).decode()
    except (ValueError, binascii.Error) as exc:
        raise ValidationError("cursor inválido") from exc
    if not symbol or symbol.strip() != symbol:
        raise ValidationError("cursor inválido")
    return symbol


__all__ = ["decode_cursor", "decode_symbol_cursor", "encode_cursor", "encode_symbol_cursor"]
