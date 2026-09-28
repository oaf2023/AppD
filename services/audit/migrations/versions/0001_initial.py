"""0001_initial — esquema inicial del Audit Service.

Nombre: 0001_initial
Fecha: 2026-09-27
Utilidad: crea el schema `audit` y la tabla append-only `records`.
Servicio: audit.
Dependencias: platform-kernel, platform-contracts.
Descripción: revisión inicial alineada con los modelos versionados.
Ejemplo de ejecución: alembic -c services/audit/alembic.ini upgrade head
Ejemplo de resultado esperado: schema `audit` con la tabla `records`.
"""

from __future__ import annotations

from alembic import op

from audit.db import SCHEMA, Base
import audit.models  # noqa: F401

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        bind.exec_driver_sql(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")
    Base.metadata.create_all(bind=bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind)
    if bind.dialect.name == "postgresql":
        bind.exec_driver_sql(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE")
