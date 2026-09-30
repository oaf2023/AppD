"""events — nombres, versiones y topics de los eventos de la plataforma (P-event-catalog).

Fase 1 en `EVENT_TYPES`/`PHASE1_TOPICS`; Fase 2 en `EVENT_TYPES_PHASE2`/`PHASE2_TOPICS`.
Naming de topics: `<dominio>.<entidad>.<evento>` (ADR-0007, P-event-catalog §3.2),
p. ej. `identity.user.registered`. DLQ: `dlq.<topic-original>`.
"""

from __future__ import annotations

import re

USER_REGISTERED = "UserRegistered"
USER_EMAIL_VERIFIED = "UserEmailVerified"
USER_LOGGED_IN = "UserLoggedIn"
LOGIN_FAILED = "LoginFailed"
MFA_ENABLED = "MfaEnabled"
MFA_DISABLED = "MfaDisabled"
SESSION_REVOKED = "SessionRevoked"
PASSWORD_RESET_REQUESTED = "PasswordResetRequested"
PASSWORD_RESET_COMPLETED = "PasswordResetCompleted"

# Fase 2 (catálogo P #38): publicado por `ledger` en el outbox del servicio.
LEDGER_POSTED = "LedgerPosted"

# Fase 2 (catálogo P #12 y #16): publicados por `accounts` en su outbox.
ACCOUNT_CREATED = "AccountCreated"
DEMO_ACCOUNT_CREATED = "DemoAccountCreated"

# Fase 2 (catálogo P #17 y #39): publicados por `accounts` en su outbox.
DEMO_BALANCE_RESET = "DemoBalanceReset"
ACCOUNT_CLOSED = "AccountClosed"

SCHEMA_VERSION = 1

EVENT_TYPES: dict[str, int] = {
    USER_REGISTERED: 1,
    USER_EMAIL_VERIFIED: 1,
    USER_LOGGED_IN: 1,
    LOGIN_FAILED: 1,
    MFA_ENABLED: 1,
    MFA_DISABLED: 1,
    SESSION_REVOKED: 1,
    PASSWORD_RESET_REQUESTED: 1,
    PASSWORD_RESET_COMPLETED: 1,
}

#: Eventos de la Fase 2 (fuera de `EVENT_TYPES`/`PHASE1_TOPICS` de la Fase 1).
EVENT_TYPES_PHASE2: dict[str, int] = {
    LEDGER_POSTED: 1,
    ACCOUNT_CREATED: 1,
    DEMO_ACCOUNT_CREATED: 1,
    DEMO_BALANCE_RESET: 1,
    ACCOUNT_CLOSED: 1,
}

EVENT_AGGREGATE_TYPE: dict[str, str] = {
    USER_REGISTERED: "User",
    USER_EMAIL_VERIFIED: "User",
    USER_LOGGED_IN: "User",
    LOGIN_FAILED: "User",
    MFA_ENABLED: "User",
    MFA_DISABLED: "User",
    SESSION_REVOKED: "Session",
    PASSWORD_RESET_REQUESTED: "User",
    PASSWORD_RESET_COMPLETED: "User",
    LEDGER_POSTED: "LedgerTransaction",
    ACCOUNT_CREATED: "TradingAccount",
    DEMO_ACCOUNT_CREATED: "TradingAccount",
    DEMO_BALANCE_RESET: "TradingAccount",
    ACCOUNT_CLOSED: "TradingAccount",
}


def _snake(name: str) -> str:
    text = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", name)
    text = re.sub(r"(?<=[A-Z])(?=[A-Z][a-z])", "_", text)
    return text.lower()


def topic_for_event(producer: str, aggregate_type: str, event_type: str) -> str:
    """Topic `<dominio>.<entidad>.<evento>` con el prefijo del agregado omitido.

    Ejemplo: `UserRegistered` de identity → `identity.user.registered`.
    """
    entity = _snake(aggregate_type)
    event = _snake(event_type)
    prefix = f"{entity}_"
    if event.startswith(prefix):
        event = event[len(prefix) :]
    return f"{producer}.{entity}.{event}"


def dlq_topic(topic: str) -> str:
    """Topic DLQ derivado: `dlq.<topic-original>`."""
    return f"dlq.{topic}"


PHASE1_TOPICS: tuple[str, ...] = tuple(
    topic_for_event("identity", EVENT_AGGREGATE_TYPE[event_type], event_type) for event_type in EVENT_TYPES
)

#: Fase 2: topics fuera del conteo `PHASE1_TOPICS` (ver test de contrato).
PHASE2_TOPICS: tuple[str, ...] = (
    topic_for_event("ledger", EVENT_AGGREGATE_TYPE[LEDGER_POSTED], LEDGER_POSTED),
    topic_for_event("accounts", EVENT_AGGREGATE_TYPE[ACCOUNT_CREATED], ACCOUNT_CREATED),
    topic_for_event("accounts", EVENT_AGGREGATE_TYPE[DEMO_ACCOUNT_CREATED], DEMO_ACCOUNT_CREATED),
    topic_for_event("accounts", EVENT_AGGREGATE_TYPE[DEMO_BALANCE_RESET], DEMO_BALANCE_RESET),
    topic_for_event("accounts", EVENT_AGGREGATE_TYPE[ACCOUNT_CLOSED], ACCOUNT_CLOSED),
)

__all__ = [
    "ACCOUNT_CLOSED",
    "ACCOUNT_CREATED",
    "DEMO_ACCOUNT_CREATED",
    "DEMO_BALANCE_RESET",
    "EVENT_AGGREGATE_TYPE",
    "EVENT_TYPES",
    "EVENT_TYPES_PHASE2",
    "LEDGER_POSTED",
    "LOGIN_FAILED",
    "MFA_DISABLED",
    "MFA_ENABLED",
    "PASSWORD_RESET_COMPLETED",
    "PASSWORD_RESET_REQUESTED",
    "PHASE1_TOPICS",
    "PHASE2_TOPICS",
    "SCHEMA_VERSION",
    "SESSION_REVOKED",
    "USER_EMAIL_VERIFIED",
    "USER_LOGGED_IN",
    "USER_REGISTERED",
    "dlq_topic",
    "topic_for_event",
]
