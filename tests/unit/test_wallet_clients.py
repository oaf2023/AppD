"""Pruebas unitarias de los clientes internos del Wallet (sin servicios remotos).

Cubre `wallet.ledger_client` y `wallet.accounts_client` con `httpx.MockTransport`:
traducciones de error HTTP/timeout (Q-api-map §3), contratos de respuesta
inválidos y posesión del `AsyncClient`. Documentado en ADR-0016 (módulos core).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import httpx
import pytest
from platform_kernel.errors import (
    ConflictError,
    NotFoundError,
    ServiceUnavailableError,
    UnauthorizedError,
    ValidationError,
)
from wallet.accounts_client import fetch_account
from wallet.ledger_client import fetch_owner_balances, post_transfer_posting

LEDGER_URL = "http://ledger.test"
ACCOUNTS_URL = "http://accounts.test"
TOKEN = "token-de-servicio"
OWNER = uuid.UUID("00000000-0000-0000-0000-0000000000a1")
OCCURRED = datetime(2026, 9, 30, 12, 0, tzinfo=UTC)


def _client(handler: httpx.MockTransport | None, raiser: Exception | None = None) -> httpx.AsyncClient:
    def _handle(request: httpx.Request) -> httpx.Response:
        if raiser is not None:
            raise raiser
        assert handler is not None
        return handler(request)

    return httpx.AsyncClient(transport=httpx.MockTransport(_handle))


# ------------------------------------------------------------------ ledger_client


async def test_ledger_client_falla_si_la_conexion_no_responde() -> None:
    client = _client(None, raiser=httpx.ConnectError("broker caído"))
    with pytest.raises(ServiceUnavailableError, match="ledger no disponible"):
        await fetch_owner_balances(ledger_url=LEDGER_URL, token=TOKEN, owner_id=OWNER, client=client)


@pytest.mark.parametrize(
    ("status", "payload", "error", "message"),
    [
        (401, {"detail": "no"}, UnauthorizedError, "token de servicio rechazado por ledger"),
        (409, {"detail": "no"}, ConflictError, "conflicto de idempotencia en ledger"),
        (500, {"detail": "no"}, ServiceUnavailableError, "ledger no disponible"),
    ],
)
async def test_ledger_client_traduce_401_409_y_5xx(status: int, payload: dict, error: type, message: str) -> None:
    client = _client(lambda request, s=status, p=payload: httpx.Response(s, json=p))
    with pytest.raises(error, match=message):
        await fetch_owner_balances(ledger_url=LEDGER_URL, token=TOKEN, owner_id=OWNER, client=client)


async def test_ledger_client_400_devuelve_el_detail_o_el_mensaje_por_defecto() -> None:
    con_detail = _client(lambda request: httpx.Response(400, json={"detail": "montos inválidos"}))
    with pytest.raises(ValidationError, match="montos inválidos"):
        await fetch_owner_balances(ledger_url=LEDGER_URL, token=TOKEN, owner_id=OWNER, client=con_detail)

    sin_detail = _client(lambda request: httpx.Response(400, json={}))
    with pytest.raises(ValidationError, match="petición rechazada por ledger"):
        await fetch_owner_balances(ledger_url=LEDGER_URL, token=TOKEN, owner_id=OWNER, client=sin_detail)


async def test_ledger_client_4xx_sin_detail_json_no_dict_o_no_json_usa_el_mensaje_generico() -> None:
    lista = _client(lambda request: httpx.Response(404, json=[1, 2]))
    with pytest.raises(ServiceUnavailableError, match="ledger respondió un error"):
        await fetch_owner_balances(ledger_url=LEDGER_URL, token=TOKEN, owner_id=OWNER, client=lista)

    html = _client(lambda request: httpx.Response(404, text="<html>404</html>"))
    with pytest.raises(ServiceUnavailableError, match="ledger respondió un error"):
        await fetch_owner_balances(ledger_url=LEDGER_URL, token=TOKEN, owner_id=OWNER, client=html)


async def test_ledger_client_200_no_json_o_no_dict_es_contrato_roto() -> None:
    client = _client(lambda request: httpx.Response(200, json={"as_of": "2026-09-30T12:00:00Z", "data": []}))
    rows, as_of = await fetch_owner_balances(ledger_url=LEDGER_URL, token=TOKEN, owner_id=OWNER, client=client)
    assert rows == [] and as_of.tzinfo is not None

    lista = _client(lambda request: httpx.Response(200, json=[1, 2]))
    with pytest.raises(ServiceUnavailableError, match="respuesta inválida de ledger"):
        await fetch_owner_balances(ledger_url=LEDGER_URL, token=TOKEN, owner_id=OWNER, client=lista)


async def test_fetch_owner_balances_rechaza_filas_malformadas() -> None:
    client = _client(
        lambda request: httpx.Response(
            200, json={"as_of": "2026-09-30T12:00:00Z", "data": [{"owner_id": "no-es-uuid"}]}
        )
    )
    with pytest.raises(ServiceUnavailableError, match="balances inválidos en ledger"):
        await fetch_owner_balances(ledger_url=LEDGER_URL, token=TOKEN, owner_id=OWNER, client=client)


async def test_post_transfer_posting_rechaza_respuesta_sin_transaction_id() -> None:
    client = _client(lambda request: httpx.Response(200, json={}))
    with pytest.raises(ServiceUnavailableError, match="posting inválido en ledger"):
        await post_transfer_posting(
            ledger_url=LEDGER_URL,
            token=TOKEN,
            idempotency_key=str(uuid.uuid4()),
            occurred_at=OCCURRED,
            entries=[],
            client=client,
        )


# --------------------------------------------------------------- accounts_client


async def test_accounts_client_falla_si_la_conexion_no_responde() -> None:
    client = _client(None, raiser=httpx.ConnectError("accounts caído"))
    with pytest.raises(ServiceUnavailableError, match="accounts no disponible"):
        await fetch_account(accounts_url=ACCOUNTS_URL, account_id=OWNER, token=TOKEN, client=client)


async def test_accounts_client_401_es_unauthorized() -> None:
    client = _client(lambda request: httpx.Response(401, json={"detail": "no"}))
    with pytest.raises(UnauthorizedError, match="token de servicio rechazado por accounts"):
        await fetch_account(accounts_url=ACCOUNTS_URL, account_id=OWNER, token=TOKEN, client=client)


async def test_accounts_client_500_es_service_unavailable() -> None:
    client = _client(lambda request: httpx.Response(503, json={"detail": "no"}))
    with pytest.raises(ServiceUnavailableError, match="accounts no disponible"):
        await fetch_account(accounts_url=ACCOUNTS_URL, account_id=OWNER, token=TOKEN, client=client)


async def test_accounts_client_404_es_not_found() -> None:
    client = _client(lambda request: httpx.Response(404, json={"detail": "no"}))
    with pytest.raises(NotFoundError, match="cuenta no encontrada"):
        await fetch_account(accounts_url=ACCOUNTS_URL, account_id=OWNER, token=TOKEN, client=client)
