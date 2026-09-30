"""ledger_client - consulta de saldos hacia el Ledger Service (Q-api-map §3).

Usado por `close` (saldo cero, §2.4) y `reload-demo` (saldo previo, BUILD-020);
la escritura es event-driven (#16/#17), no hay POST de postings en accounts
(diseño C: sin HTTP de escritura, L §7.2 / Q §3).

Espejo intencional de `wallet.ledger_client.fetch_owner_balances` (las
fronteras impiden imports cruzados entre servicios).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

import httpx
from platform_kernel.errors import ServiceUnavailableError, UnauthorizedError
from platform_kernel.money import MoneyError, to_decimal

DEFAULT_TIMEOUT = 5.0


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
    headers = {"Authorization": f"Bearer {token}"}
    url = f"{ledger_url}/internal/v1/balances"
    owns_client = client is None
    http = client if client is not None else httpx.AsyncClient(timeout=timeout)
    try:
        response = await http.get(url, params=params, headers=headers, timeout=timeout)
    except httpx.HTTPError as exc:
        raise ServiceUnavailableError("ledger no disponible") from exc
    finally:
        if owns_client:
            await http.aclose()
    if response.status_code == 401:
        raise UnauthorizedError("token de servicio rechazado por ledger")
    if response.status_code >= 400:
        raise ServiceUnavailableError("ledger no disponible")
    try:
        body: Any = response.json()
        as_of = datetime.fromisoformat(str(body["as_of"]))
        rows = [
            (uuid.UUID(str(item["owner_id"])), str(item["currency"]), to_decimal(str(item["balance"])))
            for item in body["data"]
        ]
    except (KeyError, TypeError, ValueError, MoneyError) as exc:
        raise ServiceUnavailableError("balances inválidos en ledger") from exc
    return rows, as_of


__all__ = ["DEFAULT_TIMEOUT", "fetch_owner_balances"]
