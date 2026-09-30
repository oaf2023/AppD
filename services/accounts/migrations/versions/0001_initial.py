"""0001_initial — esquema inicial del Accounts Service.

Nombre: 0001_initial
Fecha: 2026-09-30
Utilidad: crea el schema `accounts` con las tablas `trading_accounts`,
`jurisdictions` y `outbox_events`, incluida la unicidad parcial de la cuenta demo
por usuario (BUILD-020) y el índice activo por usuario (O-database-strategy §3).
Servicio: accounts.
Dependencias: platform-kernel, platform-contracts.
Descripción: revisión inicial alineada con `O-database-strategy.md` §3,
`W-build-now.md` BUILD-020/023 y `Q-api-map.md` §2.4.
Ejecución de ejemplo: alembic -c services/accounts/alembic.ini upgrade head
Resultado esperado: schema `accounts` con las 3 tablas; downgrade elimina el
schema completo (rollback BUILD-017).
"""

from __future__ import annotations

from alembic import op

from accounts.db import SCHEMA, Base
import accounts.models  # noqa: F401

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
