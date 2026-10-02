"""0002_symbol_master - symbol master versionado, sesiones, suspensiones y outbox.

Nombre: 0002_symbol_master
Fecha: 2026-10-01
Utilidad: crea las tablas del catálogo (BUILD-028, REQ-025/REQ-099):
`symbols` (identidad), `instrument_specs` (specs versionadas con una única
versión vigente por símbolo), `trading_sessions` (ventanas UTC), 
`market_suspensions` (`halted`), `market_holidays` (calendarios; seed vacío)
y `outbox` (eventos `SymbolUpdated` para el bus — drain implementado en
`market_data/outbox.py`, BUILD-029).
Sembrado idempotente del catálogo demo desde `market_data.seed` (mismo origen
de verdad que los tests): 4 símbolos mock, specs `mode: demo` y sesiones
forex 24/5 / crypto 24/7 (K §2).
Servicio: market-data.
Dependencias: platform-kernel.
Descripción: alineada con `O-database-strategy.md` §2/§9,
`K-market-data-architecture.md` §2/§4.3 y `W-build-now.md` BUILD-028.
Ejecución de ejemplo: alembic -c services/market-data/alembic.ini upgrade head
Resultado esperado: 6 tablas nuevas en el schema `market_data` + seed;
downgrade elimina solo esas tablas (ticks/candles quedan intactas).
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from market_data.db import SCHEMA, Base
import market_data.tables  # noqa: F401
from market_data.seed import seed_statements
from market_data.tables import (
    InstrumentSpecRow,
    MarketHolidayRow,
    MarketSuspensionRow,
    OutboxRow,
    SymbolRow,
    TradingSessionRow,
)

revision = "0002_symbol_master"
down_revision = "0001_initial"
branch_labels = None
depends_on = None

_NEW_TABLES = (
    SymbolRow.__table__,
    InstrumentSpecRow.__table__,
    TradingSessionRow.__table__,
    MarketSuspensionRow.__table__,
    MarketHolidayRow.__table__,
    OutboxRow.__table__,
)

_DROP_ORDER = (
    "outbox",
    "market_suspensions",
    "market_holidays",
    "trading_sessions",
    "instrument_specs",
    "symbols",
)


def upgrade() -> None:
    bind = op.get_bind()
    Base.metadata.create_all(bind=bind, checkfirst=True, tables=list(_NEW_TABLES))
    for statement in seed_statements():
        bind.execute(statement)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    for table in _DROP_ORDER:
        if inspector.has_table(table, schema=SCHEMA):
            op.drop_table(table, schema=SCHEMA)
