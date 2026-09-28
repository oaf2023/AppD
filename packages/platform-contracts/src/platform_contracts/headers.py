"""headers — cabeceras canónicas entre gateway y servicios (ADR-0017).

El gateway elimina siempre las cabeceras entrantes de este conjunto antes de
añadir las suyas: un cliente jamás puede fingir identidad.
"""

X_REQUEST_ID = "X-Request-Id"
X_CORRELATION_ID = "X-Correlation-Id"
X_USER_ID = "X-User-Id"
X_SESSION_ID = "X-Session-Id"
X_USER_ROLES = "X-User-Roles"
X_INTERNAL_TOKEN = "X-Internal-Token"

FORWARDED_HEADERS = (
    "x-user-id",
    "x-session-id",
    "x-user-roles",
    "x-internal-token",
)

__all__ = [
    "FORWARDED_HEADERS",
    "X_CORRELATION_ID",
    "X_INTERNAL_TOKEN",
    "X_REQUEST_ID",
    "X_SESSION_ID",
    "X_USER_ID",
    "X_USER_ROLES",
]
