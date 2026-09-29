"""proxy — reenvío del gateway a los servicios internos."""

from __future__ import annotations

import logging
from typing import Annotated

import httpx
from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse, PlainTextResponse
from platform_contracts.headers import (
    FORWARDED_HEADERS,
    X_CORRELATION_ID,
    X_REQUEST_ID,
    X_SESSION_ID,
    X_USER_ID,
    X_USER_ROLES,
)
from platform_contracts.roles import BACKOFFICE_ROLES
from platform_kernel.auth import AuthContext, decode_claims_optional
from platform_kernel.context import get_correlation_id, get_request_id
from platform_kernel.errors import ForbiddenError, UnauthorizedError, problem_payload
from platform_kernel.ratelimit import RateLimiter, enforce

from gateway.config import GatewaySettings, get_gateway_settings

logger = logging.getLogger("gateway.proxy")

router = APIRouter()

SettingsDep = Annotated[GatewaySettings, Depends(get_gateway_settings)]


def _limiter(request: Request) -> RateLimiter:
    return request.app.state.limiter  # type: ignore[no-any-return]


PUBLIC_PATHS: set[tuple[str, str]] = {
    ("POST", "/api/v1/auth/register"),
    ("POST", "/api/v1/auth/verify-email"),
    ("POST", "/api/v1/auth/login"),
    ("POST", "/api/v1/auth/mfa/login"),
    ("POST", "/api/v1/auth/refresh"),
    ("POST", "/api/v1/auth/password/forgot"),
    ("POST", "/api/v1/auth/password/reset"),
    ("GET", "/api/v1/market-data/overview"),
    ("GET", "/healthz"),
    ("GET", "/readyz"),
    ("GET", "/metrics"),
}

INTERNAL_PATHS = {"/docs", "/openapi.json", "/redoc"}


def _target_for(path: str) -> str | None:
    if path.startswith(("/api/v1/auth/", "/api/v1/me", "/api/v1/admin/", "/healthz", "/readyz")):
        return "identity"
    if path.startswith("/api/v1/audit-events"):
        return "audit"
    if path.startswith("/api/v1/market-data/"):
        return "market_data"
    return None


def _base_url(target: str, settings: GatewaySettings) -> str:
    urls = {"identity": settings.identity_url, "audit": settings.audit_url, "market_data": settings.market_data_url}
    return urls[target]


def _security_headers(response: Response) -> None:
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    response.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
    response.headers.setdefault("Cache-Control", "no-store")
    if get_request_id():
        response.headers.setdefault("X-Request-Id", get_request_id() or "")
    if get_correlation_id():
        response.headers.setdefault("X-Correlation-Id", get_correlation_id() or "")


def _problem(status: int, type_uri: str, title: str, detail: str) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content=problem_payload(type_uri=type_uri, title=title, status=status, detail=detail),
        media_type="application/problem+json",
    )


@router.api_route(
    "/{path:path}",
    methods=["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"],
    include_in_schema=False,
)
async def proxy(
    path: str,
    request: Request,
    settings: SettingsDep,
    limiter: Annotated[RateLimiter, Depends(_limiter)],
) -> Response:
    full_path = "/" + path
    method = request.method

    if full_path in INTERNAL_PATHS:
        return PlainTextResponse("El gateway no expone documentación interna", status_code=404)

    if method == "GET" and full_path == "/healthz":
        return await _aggregate_health(request)
    if method == "GET" and full_path == "/readyz":
        return await _aggregate_health(request, ready=True)
    if method == "GET" and full_path == "/metrics":
        return await _metrics(request)

    target = _target_for(full_path)
    if target is None:
        return _problem(404, "urn:platform:error:not-found", "No encontrado", "Ruta desconocida")

    ip = request.client.host if request.client else "unknown"
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        ip = forwarded.split(",")[0].strip()

    await enforce(request.app.state.limiter, f"gw:global:{ip}", settings.rate_limit_global_per_minute, 60)
    if full_path.startswith(settings.auth_prefixes):
        await enforce(
            request.app.state.limiter,
            f"gw:auth:{ip}",
            settings.rate_limit_auth_per_minute,
            60,
        )

    is_public = (method, full_path) in PUBLIC_PATHS
    auth: AuthContext | None = None
    if not is_public:
        auth = decode_claims_optional(request)
        if auth is None:
            raise UnauthorizedError("Autenticación requerida")
        if full_path.startswith("/api/v1/admin/") and not set(auth.roles).intersection(BACKOFFICE_ROLES):
            raise ForbiddenError("Se requieren permisos de backoffice")

    upstream_headers = _build_upstream_headers(request, auth)

    body = await request.body()
    client: httpx.AsyncClient = request.app.state.client
    url = _base_url(target, settings) + full_path
    try:
        upstream = await client.request(
            method, url, content=body, params=request.query_params, headers=upstream_headers
        )
    except httpx.TimeoutException:
        return _problem(
            504, "urn:platform:error:gateway-timeout", "Tiempo agotado", "El servicio no respondió a tiempo"
        )
    except httpx.HTTPError:
        logger.exception("upstream no disponible")
        return _problem(503, "urn:platform:error:unavailable", "No disponible", "Servicio interno no disponible")

    response = Response(
        content=upstream.content,
        status_code=upstream.status_code,
        headers=_filter_response_headers(upstream.headers),
    )
    _security_headers(response)
    return response


def _build_upstream_headers(request: Request, auth: AuthContext | None) -> dict[str, str]:
    headers: dict[str, str] = {}
    for name, value in request.headers.items():
        if name.lower() in ("host", "content-length", "connection"):
            continue
        if name.lower() in FORWARDED_HEADERS:
            continue  # jamás confiar en cabeceras de identidad del cliente
        headers[name] = value
    headers[X_REQUEST_ID] = get_request_id() or ""
    headers[X_CORRELATION_ID] = get_correlation_id() or ""
    if auth:
        headers[X_USER_ID] = auth.user_id
        headers[X_SESSION_ID] = auth.session_id
        headers[X_USER_ROLES] = ",".join(auth.roles)
    if request.client:
        existing = request.headers.get("x-forwarded-for")
        client_ip = request.client.host
        headers["X-Forwarded-For"] = f"{existing}, {client_ip}" if existing else client_ip
    return headers


def _filter_response_headers(headers: httpx.Headers) -> dict[str, str]:
    excluded = {"content-length", "transfer-encoding", "connection", "keep-alive"}
    return {k: v for k, v in headers.items() if k.lower() not in excluded}


async def _aggregate_health(request: Request, ready: bool = False) -> Response:
    client: httpx.AsyncClient = request.app.state.client
    settings = get_gateway_settings()
    checks: dict[str, str] = {}
    all_ok = True
    for name, base in (
        ("identity", settings.identity_url),
        ("audit", settings.audit_url),
        ("market_data", settings.market_data_url),
    ):
        path = "/readyz" if ready else "/healthz"
        try:
            r = await client.get(f"{base}{path}")
            checks[name] = "ok" if r.status_code == 200 else f"error:{r.status_code}"
        except httpx.HTTPError:
            checks[name] = "unreachable"
        all_ok = all_ok and checks[name] == "ok"
    status = 200 if all_ok else 503
    return JSONResponse(
        status_code=status,
        content={"service": "gateway", "status": "ok" if all_ok else "degraded", "checks": checks},
    )


async def _metrics(request: Request) -> Response:
    from platform_kernel.metrics import metrics_response

    return metrics_response()


__all__ = ["PUBLIC_PATHS", "router"]
