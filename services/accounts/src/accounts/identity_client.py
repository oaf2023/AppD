"""identity_client — cliente HTTP del endpoint interno de `identity` (Q-api-map §3).

`GET /internal/v1/users/{user_id}` (perfil mínimo: jurisdicción del caller) con
JWT de servicio; timeout acotado y errores tipados. Sin acoplamiento: solo HTTP
en la frontera (ADR-0001).
"""

from __future__ import annotations

import uuid

import httpx
from platform_kernel.errors import NotFoundError, ServiceUnavailableError, UnauthorizedError
from platform_kernel.security.tokens import new_service_token

from accounts.schemas import UserProfile

INTERNAL_USERS_PATH = "/internal/v1/users"
MAX_ERROR_LENGTH = 2000


def service_token(*, service_name: str, secret: str, issuer: str, audience: str) -> str:
    return new_service_token(service_name=service_name, secret=secret, issuer=issuer, audience=audience)


async def fetch_user_profile(
    *,
    identity_url: str,
    user_id: uuid.UUID,
    token: str,
    client: httpx.AsyncClient | None = None,
    timeout: float = 5.0,
) -> UserProfile:
    """Obtiene el perfil mínimo de un usuario desde identity.

    - 404 → `NotFoundError` (usuario inexistente).
    - 401/403 → `UnauthorizedError` (token de servicio rechazado).
    - Timeout/5xx → `ServiceUnavailableError` (identity degradado).
    """
    url = f"{identity_url.rstrip('/')}{INTERNAL_USERS_PATH}/{user_id}"
    headers = {"Authorization": f"Bearer {token}"}
    owns_client = client is None
    http = client or httpx.AsyncClient(timeout=timeout)
    try:
        response = await http.get(url, headers=headers)
    except httpx.TimeoutException as exc:
        raise ServiceUnavailableError("identity no responde (timeout)") from exc
    except httpx.HTTPError as exc:
        raise ServiceUnavailableError(f"identity inaccesible: {str(exc)[:MAX_ERROR_LENGTH]}") from exc
    finally:
        if owns_client:
            await http.aclose()

    if response.status_code == 404:
        raise NotFoundError("usuario")
    if response.status_code in (401, 403):
        raise UnauthorizedError("Token de servicio rechazado por identity")
    if response.status_code >= 500:
        raise ServiceUnavailableError(f"identity devolvió {response.status_code}")
    if response.status_code != 200:
        raise ServiceUnavailableError(f"identity devolvió {response.status_code} inesperado")
    return UserProfile.model_validate(response.json())


__all__ = ["INTERNAL_USERS_PATH", "fetch_user_profile", "service_token"]
