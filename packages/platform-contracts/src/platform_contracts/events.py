"""events — nombres y versiones de eventos de la Fase 1 (catálogo P-event-catalog)."""

from __future__ import annotations

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

__all__ = [
    "EVENT_TYPES",
    "LOGIN_FAILED",
    "MFA_DISABLED",
    "MFA_ENABLED",
    "PASSWORD_RESET_COMPLETED",
    "PASSWORD_RESET_REQUESTED",
    "SCHEMA_VERSION",
    "SESSION_REVOKED",
    "USER_EMAIL_VERIFIED",
    "USER_LOGGED_IN",
    "USER_REGISTERED",
]
