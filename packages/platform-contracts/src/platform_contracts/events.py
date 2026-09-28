"""events — nombres, versiones y topics de los eventos de la Fase 1 (catálogo P-event-catalog).

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

__all__ = [
    "EVENT_AGGREGATE_TYPE",
    "EVENT_TYPES",
    "LOGIN_FAILED",
    "MFA_DISABLED",
    "MFA_ENABLED",
    "PASSWORD_RESET_COMPLETED",
    "PASSWORD_RESET_REQUESTED",
    "PHASE1_TOPICS",
    "SCHEMA_VERSION",
    "SESSION_REVOKED",
    "USER_EMAIL_VERIFIED",
    "USER_LOGGED_IN",
    "USER_REGISTERED",
    "dlq_topic",
    "topic_for_event",
]
