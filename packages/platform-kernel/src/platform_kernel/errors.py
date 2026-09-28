"""errors — modelo de error único del sistema (RFC 9457 problem+json).

Todo servicio devuelve errores con este formato. `request_id` y `correlation_id`
son obligatorios para poder correlacionar con logs y auditoría.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from platform_kernel.context import get_correlation_id, get_request_id

logger = logging.getLogger("platform.errors")

PROBLEM_MEDIA_TYPE = "application/problem+json"


class AppError(Exception):
    """Error de aplicación con tipo RFC 9457 estable."""

    def __init__(
        self,
        status_code: int,
        type_uri: str,
        title: str,
        detail: str | None = None,
        *,
        extra: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(detail or title)
        self.status_code = status_code
        self.type_uri = type_uri
        self.title = title
        self.detail = detail
        self.extra = extra or {}


class ValidationError(AppError):
    def __init__(self, detail: str | None = None, *, errors: list[Any] | None = None) -> None:
        super().__init__(
            422,
            "urn:platform:error:validation",
            "Validación fallida",
            detail,
            extra={"errors": errors or []},
        )


class UnauthorizedError(AppError):
    def __init__(self, detail: str = "Credenciales inválidas") -> None:
        super().__init__(401, "urn:platform:error:unauthorized", "No autorizado", detail)


class ForbiddenError(AppError):
    def __init__(self, detail: str = "Permisos insuficientes") -> None:
        super().__init__(403, "urn:platform:error:forbidden", "Prohibido", detail)


class NotFoundError(AppError):
    def __init__(self, resource: str = "recurso") -> None:
        super().__init__(404, "urn:platform:error:not-found", "No encontrado", f"{resource} no existe")


class ConflictError(AppError):
    def __init__(self, detail: str) -> None:
        super().__init__(409, "urn:platform:error:conflict", "Conflicto", detail)


class RateLimitedError(AppError):
    def __init__(self, retry_after: int) -> None:
        super().__init__(
            429,
            "urn:platform:error:rate-limited",
            "Demasiadas solicitudes",
            "Límite de velocidad excedido",
            extra={"retry_after": retry_after},
        )


class ServiceUnavailableError(AppError):
    def __init__(self, detail: str = "Servicio no disponible") -> None:
        super().__init__(503, "urn:platform:error:unavailable", "No disponible", detail)


def problem_payload(
    *,
    type_uri: str,
    title: str,
    status: int,
    detail: str | None = None,
    instance: str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "type": type_uri,
        "title": title,
        "status": status,
        "request_id": get_request_id(),
        "correlation_id": get_correlation_id(),
    }
    if detail:
        payload["detail"] = detail
    if instance:
        payload["instance"] = instance
    if extra:
        payload.update(extra)
    return payload


def _response(request: Request, payload: dict[str, Any], status: int) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content=payload,
        media_type=PROBLEM_MEDIA_TYPE,
        headers={"X-Request-Id": get_request_id() or "", "X-Correlation-Id": get_correlation_id() or ""},
    )


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def _app_error(request: Request, exc: AppError) -> JSONResponse:  # type: ignore[misc]
        return _response(
            request,
            problem_payload(
                type_uri=exc.type_uri,
                title=exc.title,
                status=exc.status_code,
                detail=exc.detail,
                instance=str(request.url.path),
                extra=exc.extra,
            ),
            exc.status_code,
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:  # type: ignore[misc]
        detail = str(exc.detail) if exc.detail else None
        return _response(
            request,
            problem_payload(
                type_uri=f"urn:platform:error:http:{exc.status_code}",
                title="Error HTTP",
                status=exc.status_code,
                detail=detail,
                instance=str(request.url.path),
            ),
            exc.status_code,
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:  # type: ignore[misc]
        return _response(
            request,
            problem_payload(
                type_uri="urn:platform:error:validation",
                title="Validación fallida",
                status=422,
                detail="Cuerpo o parámetros inválidos",
                instance=str(request.url.path),
                extra={"errors": exc.errors()},
            ),
            422,
        )

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:  # type: ignore[misc]
        logger.error(
            "error no controlado en %s %s",
            request.method,
            request.url.path,
            exc_info=exc,
        )
        return _response(
            request,
            problem_payload(
                type_uri="urn:platform:error:internal",
                title="Error interno",
                status=500,
                detail="Error interno del servidor",
                instance=str(request.url.path),
            ),
            500,
        )


__all__ = [
    "PROBLEM_MEDIA_TYPE",
    "AppError",
    "ConflictError",
    "ForbiddenError",
    "NotFoundError",
    "RateLimitedError",
    "ServiceUnavailableError",
    "UnauthorizedError",
    "ValidationError",
    "install_error_handlers",
    "problem_payload",
]
