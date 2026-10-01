"""0001_initial - esquema inicial del Market Data Service.

Nombre: 0001_initial
Fecha: 2026-10-01
Utilidad: crea el schema `market_data` con las tablas `ticks` y `candles`.
`ticks` deduplica por `(symbol, source, ts, price)` (K §4.4 sin provider_seq);
`candles` codifica los huecos explícitos K §4.4(c) (`gap=true` ⇒ OHLC/volumen
NULL) y las invariantes REQ-028 (`low <= min(open, close)`,
`high >= max(open, close)`) como CHECK a nivel de BD.
Servicio: market-data.
Dependencias: platform-kernel, platform-contracts.
Descripción: alineada con `O-database-strategy.md` §2/§9 (retención 2a ticks /
7a velas = pendiente), `K-market-data-architecture.md` §4.4 y
`W-build-now.md` BUILD-027. Postgres 17 plano: TimescaleDB/particionado
quedan como DECIDIR (M §97, O §201).
Ejecución de ejemplo: alembic -c services/market-data/alembic.ini upgrade head
Resultado esperado: schema `market_data` con las 2 tablas; downgrade elimina el schema completo.
"""

from __future__ import annotations

from alembic import op

from market_data.db import SCHEMA, Base
import market_data.tables  # noqa: F401

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
