"""ledger_client - llamadas internas hacia el Ledger Service (Q-api-map §3).

Fuente de verdad de saldos (`GET /internal/v1/balances`) y única vía de
escritura (`POST /internal/v1/postings`). Token de servicio obligatorio.
Las traducciones de error usan los tipos del kernel: 401 → `UnauthorizedError`,
409 → `ConflictError`, 400 → `ValidationError`, 5xx/timeout → `ServiceUnavailableError`.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

import httpx
from platform_kernel.errors import ConflictError, ServiceUnavailableError, UnauthorizedError, ValidationError
from platform_kernel.money import MoneyError, to_decimal

DEFAULT_TIMEOUT = 5.0


async def _request(
    *,
    method: str,
    url: str,
    token: str,
    json: dict[str, Any] | None = None,
    params: dict[str, str] | None = None,
    idempotency_key: str | None = None,
    client: httpx.AsyncClient | None = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> dict[str, Any]:
    headers = {"Authorization": f"Bearer {token}"}
    if idempotency_key is not None:
        headers["Idempotency-Key"] = idempotency_key
    owns_client = client is None
    http = client if client is not None else httpx.AsyncClient(timeout=timeout)
    try:
        response = await http.request(method, url, json=json, params=params, headers=headers, timeout=timeout)
    except httpx.HTTPError as exc:
        raise ServiceUnavailableError("ledger no disponible") from exc
    finally:
        if owns_client:
            await http.aclose()
    if response.status_code == 401:
        raise UnauthorizedError("token de servicio rechazado por ledger")
    if response.status_code == 409:
        raise ConflictError("conflicto de idempotencia en ledger")
    if response.status_code == 400:
        raise ValidationError(_detail(response) or "petición rechazada por ledger")
    if response.status_code >= 500:
        raise ServiceUnavailableError("ledger no disponible")
    if response.status_code >= 400:
        raise ServiceUnavailableError(_detail(response) or "ledger respondió un error")
    try:
        body: Any = response.json()
    except ValueError as exc:  # pragma: no cover - contrato roto
        raise ServiceUnavailableError("respuesta inválida de ledger") from exc
    if not isinstance(body, dict):
        raise ServiceUnavailableError("respuesta inválida de ledger")
    return body


def _detail(response: httpx.Response) -> str | None:
    try:
        body = response.json()
    except ValueError:
        return None
    detail = body.get("detail") if isinstance(body, dict) else None
    return str(detail)[:200] if detail else None


async def fetch_owner_balances(
    *,
    ledger_url: str,
    token: str,
    owner_id: uuid.UUID | None,
    client: httpx.AsyncClient | None = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> tuple[list[tuple[uuid.UUID, str, Decimal]], datetime]:
    """`GET /internal/v1/balances` → [(owner_id, currency, saldo)] + as_of."""
    params = {"owner_id": str(owner_id)} if owner_id is not None else None
    body = await _request(
        method="GET",
        url=f"{ledger_url}/internal/v1/balances",
        token=token,
        params=params,
        client=client,
        timeout=timeout,
    )
    try:
        as_of = datetime.fromisoformat(str(body["as_of"]))
        rows = [
            (uuid.UUID(str(item["owner_id"])), str(item["currency"]), to_decimal(str(item["balance"])))
            for item in body["data"]
        ]
    except (KeyError, TypeError, ValueError, MoneyError) as exc:
        raise ServiceUnavailableError("balances inválidos en ledger") from exc
    return rows, as_of


async def post_transfer_posting(
    *,
    ledger_url: str,
    token: str,
    idempotency_key: str,
    occurred_at: datetime,
    entries: list[dict[str, Any]],
    client: httpx.AsyncClient | None = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> uuid.UUID:
    """`POST /internal/v1/postings` (type=transfer) → transaction_id."""
    body = await _request(
        method="POST",
        url=f"{ledger_url}/internal/v1/postings",
        token=token,
        json={
            "type": "transfer",
            "correlation_id": idempotency_key,
            "causation_id": None,
            "occurred_at": occurred_at.isoformat(),
            "metadata": {"source": "wallet.transfer"},
            "entries": entries,
        },
        idempotency_key=idempotency_key,
        client=client,
        timeout=timeout,
    )
    try:
        return uuid.UUID(str(body["transaction_id"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise ServiceUnavailableError("posting inválido en ledger") from exc


__all__ = ["DEFAULT_TIMEOUT", "fetch_owner_balances", "post_transfer_posting"]
