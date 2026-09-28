"""Pruebas unitarias de contratos compartidos (roles, eventos, headers)."""

from __future__ import annotations

from platform_contracts.events import EVENT_TYPES, SCHEMA_VERSION, USER_REGISTERED
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


def test_headers_de_identidad_no_se_confian_al_cliente() -> None:
    assert "x-user-id" in FORWARDED_HEADERS
    assert "x-session-id" in FORWARDED_HEADERS
    assert "x-user-roles" in FORWARDED_HEADERS
