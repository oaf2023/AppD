"""logging — estructurado, con contexto de trazabilidad y redacción de secretos."""

from __future__ import annotations

import json
import logging
import sys
import time
from typing import Any

from platform_kernel.context import get_context

_SENSITIVE_KEYS = {
    "password",
    "new_password",
    "old_password",
    "token",
    "refresh_token",
    "access_token",
    "secret",
    "api_key",
    "apikey",
    "authorization",
    "mfa_secret",
    "private_key",
}


def redact(data: dict[str, Any]) -> dict[str, Any]:
    """Redacción defensiva: nunca registrar secretos ni PII sensible (G §9)."""
    out: dict[str, Any] = {}
    for key, value in data.items():
        if key.lower() in _SENSITIVE_KEYS:
            out[key] = "[REDACTED]"
        elif isinstance(value, dict):
            out[key] = redact(value)
        else:
            out[key] = value
    return out


class JsonFormatter(logging.Formatter):
    def __init__(self, service: str) -> None:
        super().__init__()
        self._service = service

    def format(self, record: logging.LogRecord) -> str:
        ctx = get_context()
        payload: dict[str, Any] = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(record.created)) + f".{int(record.msecs):03d}Z",
            "level": record.levelname,
            "service": self._service,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": ctx.request_id,
            "correlation_id": ctx.correlation_id,
            "user_id": ctx.user_id,
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        extra = getattr(record, "extra_fields", None)
        if isinstance(extra, dict):
            payload.update(redact(extra))
        return json.dumps(payload, ensure_ascii=False, default=str)


def setup_logging(service: str, level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter(service))
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level.upper())
    logging.getLogger("uvicorn.access").handlers.clear()


def log_event(logger: logging.Logger, message: str, **fields: Any) -> None:
    logger.info(message, extra={"extra_fields": fields})


__all__ = ["JsonFormatter", "log_event", "redact", "setup_logging"]
