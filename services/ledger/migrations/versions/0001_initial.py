"""0001_initial — esquema inicial del Ledger Service.

Nombre: 0001_initial
Fecha: 2026-09-29
Utilidad: crea el schema `ledger` con las tablas de cuentas, transacciones,
asientos, idempotencia, snapshots y outbox, más las garantías de append-only y
de balance (trigger + REVOKE + `ledger.ledger_assert_balanced`).
Servicio: ledger.
Dependencias: platform-kernel, platform-contracts.
Descripción: revisión inicial alineada con `L-ledger-architecture.md` §2.1-§2.3,
§3, §4.1 y §5, y con ADR-0011 §1-§5.
Ejemplo de ejecución: alembic -c services/ledger/alembic.ini upgrade head
Ejemplo de resultado esperado: schema `ledger` con las 6 tablas, la vista
`ledger_account_balances` y los triggers anti-modificación.
"""

from __future__ import annotations

from alembic import op

from ledger.db import SCHEMA, Base
import ledger.models  # noqa: F401

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None

# L §2.2: función de defensa en profundidad invocada por la app antes del COMMIT.
ASSERT_BALANCED_SQL = """
CREATE OR REPLACE FUNCTION ledger.ledger_assert_balanced(tx_id uuid) RETURNS void
LANGUAGE plpgsql AS $$
DECLARE diff numeric;
BEGIN
    SELECT SUM(CASE WHEN direction = 'D' THEN amount ELSE -amount END)
      INTO diff FROM ledger.ledger_entries WHERE transaction_id = tx_id;
    IF diff IS NOT NULL AND diff <> 0 THEN
        RAISE EXCEPTION 'Transaction %% not balanced: net %%', tx_id, diff;
    END IF;
END;
$$;
"""

# ADR-0011 §2: el REVOKE no es observable porque el usuario `platform` es
# superuser; el trigger con ERRCODE 42501 sí lo es (y protege a todo rol).
FORBID_MUTATION_SQL = """
CREATE OR REPLACE FUNCTION ledger.ledger_forbid_mutation() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'ledger es append-only: %% sobre %% prohibido', TG_OP, TG_TABLE_NAME
        USING ERRCODE = '42501';
END;
$$;
"""

IMMUTABLE_TABLES = ("ledger_entries", "ledger_transactions")

REVOKE_SQL = "REVOKE UPDATE, DELETE, TRUNCATE ON ALL TABLES IN SCHEMA ledger FROM PUBLIC"

BALANCES_VIEW_SQL = """
CREATE OR REPLACE VIEW ledger.ledger_account_balances AS
SELECT
    la.id AS account_id,
    la.code,
    la.currency,
    COALESCE(SUM(CASE WHEN le.direction = 'D' THEN le.amount ELSE -le.amount END), 0) AS balance
FROM ledger.ledger_accounts la
LEFT JOIN ledger.ledger_entries le ON le.account_id = la.id
GROUP BY la.id, la.code, la.currency
"""


def _install_guarantees(bind) -> None:  # type: ignore[no-untyped-def]
    bind.exec_driver_sql(ASSERT_BALANCED_SQL)
    bind.exec_driver_sql(FORBID_MUTATION_SQL)
    for table in IMMUTABLE_TABLES:
        bind.exec_driver_sql(f"DROP TRIGGER IF EXISTS trg_{table}_immutable ON {SCHEMA}.{table}")
        bind.exec_driver_sql(
            f"CREATE TRIGGER trg_{table}_immutable "
            f"BEFORE UPDATE OR DELETE ON {SCHEMA}.{table} "
            f"FOR EACH ROW EXECUTE FUNCTION {SCHEMA}.ledger_forbid_mutation()"
        )
    bind.exec_driver_sql(REVOKE_SQL)
    bind.exec_driver_sql(BALANCES_VIEW_SQL)


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        bind.exec_driver_sql(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}")
    Base.metadata.create_all(bind=bind, checkfirst=True)
    if bind.dialect.name == "postgresql":
        _install_guarantees(bind)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        for table in IMMUTABLE_TABLES:
            bind.exec_driver_sql(f"DROP TRIGGER IF EXISTS trg_{table}_immutable ON {SCHEMA}.{table}")
        bind.exec_driver_sql(f"DROP VIEW IF EXISTS {SCHEMA}.ledger_account_balances")
        bind.exec_driver_sql(f"DROP FUNCTION IF EXISTS {SCHEMA}.ledger_forbid_mutation()")
        bind.exec_driver_sql(f"DROP FUNCTION IF EXISTS {SCHEMA}.ledger_assert_balanced(uuid)")
    Base.metadata.drop_all(bind=bind)
    if bind.dialect.name == "postgresql":
        bind.exec_driver_sql(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE")
