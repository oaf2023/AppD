"""0001_initial — esquema inicial del Identity Service.

Nombre: 0001_initial
Fecha: 2026-09-27
Utilidad: crea el schema `identity` y todas las tablas iniciales del servicio.
Servicio: identity.
Dependencias: platform-kernel, platform-contracts.
Descripción: revisión inicial; se usa `Base.metadata.create_all` para garantizar
que el esquema creado coincida 1:1 con los modelos versionados en el repositorio.
Ejemplo de ejecución: alembic -c services/identity/alembic.ini upgrade head
Ejemplo de resultado esperado: schema `identity` con 9 tablas creadas.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from identity.db import SCHEMA, Base
import identity.models  # noqa: F401

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def _create_schema(connection) -> None:  # type: ignore[no-untyped-def]
    if connection.dialect.name == "postgresql":
        connection.exec_driver_sql(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")
    elif connection.dialect.name == "sqlite":
        pass  # SQLite no usa schemas; los modelos se resuelven sin esquema


def upgrade() -> None:
    bind = op.get_bind()
    _create_schema(bind)
    Base.metadata.create_all(bind=bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind)
    if bind.dialect.name == "postgresql":
        bind.exec_driver_sql(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE")
