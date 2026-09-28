"""roles — catálogo de roles RBAC (G §4). Denegación por defecto."""

from __future__ import annotations

from typing import Literal

Role = Literal[
    "user",
    "support",
    "compliance",
    "kyc-analyst",
    "risk-operator",
    "maker",
    "checker",
    "admin",
    "superadmin",
]

ALL_ROLES: tuple[str, ...] = (
    "user",
    "support",
    "compliance",
    "kyc-analyst",
    "risk-operator",
    "maker",
    "checker",
    "admin",
    "superadmin",
)

BACKOFFICE_ROLES: tuple[str, ...] = (
    "support",
    "compliance",
    "kyc-analyst",
    "risk-operator",
    "maker",
    "checker",
    "admin",
    "superadmin",
)

DEFAULT_ROLES: tuple[str, ...] = ("user",)


def is_valid_role(role: str) -> bool:
    return role in ALL_ROLES


__all__ = ["ALL_ROLES", "BACKOFFICE_ROLES", "DEFAULT_ROLES", "Role", "is_valid_role"]
