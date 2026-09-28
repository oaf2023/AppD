"""0002_outbox_relay — columnas de estado del relay outbox → Redpanda.

Nombre: 0002_outbox_relay
Fecha: 2026-09-28
Utilidad: renombra `attempts` → `publish_attempts` y añade `next_attempt_at`,
`dead_lettered_at` (y `last_error` si faltara) en `outbox_events`.
Servicio: identity.
Dependencias: 0001_initial.
Descripción: migración idempotente (0001 usa `create_all`, así que una BD fresca
ya puede contener estas columnas); las guardas por inspector siguen ADR-0014 §6.
Ejemplo de ejecución: alembic -c services/identity/alembic.ini upgrade head
Ejemplo de resultado esperado: `outbox_events` con las 4 columnas de reintentos.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from identity.db import SCHEMA

revision = "0002_outbox_relay"
down_revision = "0001_initial"
branch_labels = None
depends_on = None

TABLE = "outbox_events"


def _columns() -> set[str]:
    return {c["name"] for c in sa.inspect(op.get_bind()).get_columns(TABLE, schema=SCHEMA)}


def upgrade() -> None:
    columns = _columns()
    if "attempts" in columns and "publish_attempts" not in columns:
        op.alter_column(TABLE, "attempts", new_column_name="publish_attempts", schema=SCHEMA)
        columns.discard("attempts")
        columns.add("publish_attempts")
    if "publish_attempts" not in columns:
        op.add_column(
            TABLE,
            sa.Column("publish_attempts", sa.Integer(), nullable=False, server_default="0"),
            schema=SCHEMA,
        )
    if "next_attempt_at" not in columns:
        op.add_column(TABLE, sa.Column("next_attempt_at", sa.DateTime(timezone=True)), schema=SCHEMA)
    if "dead_lettered_at" not in columns:
        op.add_column(TABLE, sa.Column("dead_lettered_at", sa.DateTime(timezone=True)), schema=SCHEMA)
    if "last_error" not in columns:
        op.add_column(TABLE, sa.Column("last_error", sa.Text()), schema=SCHEMA)


def downgrade() -> None:
    columns = _columns()
    if "next_attempt_at" in columns:
        op.drop_column(TABLE, "next_attempt_at", schema=SCHEMA)
    if "dead_lettered_at" in columns:
        op.drop_column(TABLE, "dead_lettered_at", schema=SCHEMA)
    if "publish_attempts" in columns and "attempts" not in columns:
        op.alter_column(TABLE, "publish_attempts", new_column_name="attempts", schema=SCHEMA)
    # `last_error` existía desde 0001: no se elimina en el downgrade
