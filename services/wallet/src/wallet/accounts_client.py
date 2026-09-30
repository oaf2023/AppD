"""accounts_client - consulta de cuentas hacia el Accounts Service (Q-api-map §3).

Wallet valida que el origen le pertenezca al caller (BOLA) y que ambas cuentas
estén activas y en el mismo modo/moneda antes de escribir en el ledger.
"""

from __future__ import annotations

import uuid

import httpx
from platform_kernel.errors import NotFoundError, ServiceUnavailableError, UnauthorizedError

from wallet.schemas import AccountRef

DEFAULT_TIMEOUT = 5.0


async def fetch_account(
    *,
    accounts_url: str,
    account_id: uuid.UUID,
    token: str,
    client: httpx.AsyncClient | None = None,
    timeout: float = DEFAULT_TIMEOUT,
) -> AccountRef:
    """`GET /internal/v1/accounts/{id}`; 404 → `NotFoundError` (BOLA §1.7.3)."""
    headers = {"Authorization": f"Bearer {token}"}
    url = f"{accounts_url}/internal/v1/accounts/{account_id}"
    owns_client = client is None
    http = client if client is not None else httpx.AsyncClient(timeout=timeout)
    try:
        response = await http.get(url, headers=headers, timeout=timeout)
    except httpx.HTTPError as exc:
        raise ServiceUnavailableError("accounts no disponible") from exc
    finally:
        if owns_client:
            await http.aclose()
    if response.status_code == 404:
        raise NotFoundError("cuenta no encontrada")
    if response.status_code == 401:
        raise UnauthorizedError("token de servicio rechazado por accounts")
    if response.status_code >= 400:
        raise ServiceUnavailableError("accounts no disponible")
    try:
        return AccountRef.model_validate(response.json())
    except ValueError as exc:  # pragma: no cover - contrato roto
        raise ServiceUnavailableError("respuesta inválida de accounts") from exc


__all__ = ["DEFAULT_TIMEOUT", "fetch_account"]
