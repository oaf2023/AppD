"""0003_outbox_relay — columnas de estado del relay outbox → Redpanda.

Nombre: 0003_outbox_relay
Fecha: 2026-10-01
Utilidad: añade a `outbox` las columnas del relay (BUILD-029, K §4.2):
`published_at`, `publish_attempts`, `next_attempt_at`, `last_error`,
`dead_lettered_at` + índice parcial `ix_outbox_pending` (pendientes de
publicar). Servicio: market-data.
Dependencias: 0002_symbol_master.
Descripción: migración idempotente (0002 usa `create_all`, así que una BD
fresca ya puede contener estas columnas); las guardas por inspector siguen
ADR-0014 §6 (mismo patrón que `identity/0002_outbox_relay`).
Ejemplo de ejecución: alembic -c services/market-data/alembic.ini upgrade head
Ejemplo de resultado esperado: `outbox` con las 5 columnas de reintentos.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from market_data.db import SCHEMA

revision = "0003_outbox_relay"
down_revision = "0002_symbol_master"
branch_labels = None
depends_on = None

TABLE = "outbox"

_RELAY_COLUMNS = (
    sa.Column("published_at", sa.DateTime(timezone=True)),
    sa.Column("next_attempt_at", sa.DateTime(timezone=True)),
    sa.Column("dead_lettered_at", sa.DateTime(timezone=True)),
    sa.Column("last_error", sa.String(2000)),
    sa.Column("publish_attempts", sa.Integer(), nullable=False, server_default="0"),
)


def _inspector() -> sa.Inspector:
    return sa.inspect(op.get_bind())


def upgrade() -> None:
    inspector = _inspector()
    columns = {c["name"] for c in inspector.get_columns(TABLE, schema=SCHEMA)}
    for column in _RELAY_COLUMNS:
        if column.name not in columns:
            op.add_column(TABLE, column, schema=SCHEMA)
    indexes = {i["name"] for i in inspector.get_indexes(TABLE, schema=SCHEMA)}
    if "ix_outbox_pending" not in indexes:
        op.create_index(
            "ix_outbox_pending",
            TABLE,
            ["created_at"],
            unique=False,
            schema=SCHEMA,
            postgresql_where=sa.text("published_at IS NULL AND dead_lettered_at IS NULL"),
        )


def downgrade() -> None:
    inspector = _inspector()
    indexes = {i["name"] for i in inspector.get_indexes(TABLE, schema=SCHEMA)}
    if "ix_outbox_pending" in indexes:
        op.drop_index("ix_outbox_pending", table_name=TABLE, schema=SCHEMA)
    columns = {c["name"] for c in inspector.get_columns(TABLE, schema=SCHEMA)}
    for name in ("dead_lettered_at", "next_attempt_at", "published_at", "last_error", "publish_attempts"):
        if name in columns:
            op.drop_column(TABLE, name, schema=SCHEMA)
