"""Pruebas unitarias de contratos compartidos (roles, eventos, headers)."""

from __future__ import annotations

from platform_contracts.events import (
    EVENT_AGGREGATE_TYPE,
    EVENT_TYPES,
    LEDGER_POSTED,
    PHASE1_TOPICS,
    PHASE2_TOPICS,
    SCHEMA_VERSION,
    USER_REGISTERED,
    dlq_topic,
    topic_for_event,
)
from platform_contracts.headers import FORWARDED_HEADERS
from platform_contracts.roles import ALL_ROLES, BACKOFFICE_ROLES, DEFAULT_ROLES, is_valid_role


def test_roles_backoffice_excluye_user() -> None:
    assert "user" not in BACKOFFICE_ROLES
    assert set(BACKOFFICE_ROLES).issubset(set(ALL_ROLES))
    assert DEFAULT_ROLES == ("user",)


def test_roles_validos() -> None:
    assert is_valid_role("admin")
    assert not is_valid_role("root")


def test_catalogo_eventos_fase1() -> None:
    assert len(EVENT_TYPES) == 9
    assert EVENT_TYPES[USER_REGISTERED] == SCHEMA_VERSION == 1


def test_naming_de_topics_de_la_fase1() -> None:
    assert topic_for_event("identity", "User", "UserRegistered") == "identity.user.registered"
    assert topic_for_event("identity", "Session", "SessionRevoked") == "identity.session.revoked"
    assert topic_for_event("identity", "User", "LoginFailed") == "identity.user.login_failed"
    assert dlq_topic("identity.user.registered") == "dlq.identity.user.registered"
    assert len(PHASE1_TOPICS) == 9
    assert "identity.session.revoked" in PHASE1_TOPICS
    assert all(not topic.startswith("identity.user_") for topic in PHASE1_TOPICS)


def test_evento_ledger_posted_fase2() -> None:
    """Catálogo P #38: `LedgerPosted` vive fuera de EVENT_TYPES/PHASE1_TOPICS (Fase 1)."""
    assert LEDGER_POSTED == "LedgerPosted"
    assert EVENT_AGGREGATE_TYPE[LEDGER_POSTED] == "LedgerTransaction"
    assert PHASE2_TOPICS == ("ledger.ledger_transaction.ledger_posted",)
    assert LEDGER_POSTED not in EVENT_TYPES
    assert len(EVENT_TYPES) == 9
    assert len(PHASE1_TOPICS) == 9


def test_headers_de_identidad_no_se_confian_al_cliente() -> None:
    assert "x-user-id" in FORWARDED_HEADERS
    assert "x-session-id" in FORWARDED_HEADERS
    assert "x-user-roles" in FORWARDED_HEADERS
