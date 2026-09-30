"""0001_initial - esquema inicial del Wallet Service.

Nombre: 0001_initial
Fecha: 2026-09-30
Utilidad: crea el schema `wallet` con las tablas `balances`, `balance_movements`,
`processed_events`, `balance_snapshots`, `currency_config` y `conversion_rates`,
más la semilla ISO 4217 de USD (moneda demo). Incluye el índice único
`idx_bal_user_curr (user_id, currency)` de O-database-strategy §5.2, adaptado a
sin predicado: `balances` no usa `deleted_at` en F2 (la proyección es de estado,
no de entidad borrable).
Servicio: wallet.
Dependencias: platform-kernel, platform-contracts.
Descripción: alineada con `O-database-strategy.md` §2/§5.2/§9, `L-ledger-architecture.md`
§4.1 (proyección wallet) y `W-build-now.md` BUILD-019/021/022.
Ejecución de ejemplo: alembic -c services/wallet/alembic.ini upgrade head
Resultado esperado: schema `wallet` con las 6 tablas; downgrade elimina el schema completo.
"""

from __future__ import annotations

from alembic import op

from wallet.db import SCHEMA, Base
import wallet.models  # noqa: F401

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        bind.exec_driver_sql(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")
    Base.metadata.create_all(bind=bind, checkfirst=True)
    if bind.dialect.name == "postgresql":
        # Semilla: USD es la moneda de la cuenta demo (ISO 4217: 2 decimales).
        bind.exec_driver_sql(
            """
            INSERT INTO wallet.currency_config (currency, decimals, symbol, is_active)
            VALUES ('USD', 2, '$', TRUE)
            ON CONFLICT (currency) DO NOTHING
            """
        )


def downgrade() -> None:
    bind = op.get_bind()
    Base.metadata.drop_all(bind=bind)
    if bind.dialect.name == "postgresql":
        bind.exec_driver_sql(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE")
