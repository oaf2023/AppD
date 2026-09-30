"""conftest raíz — fixtures compartidas de la suite (PostgreSQL obligatorio)."""

from __future__ import annotations

import helpers  # noqa: F401 — fija las variables de entorno antes de importar servicios
import platform_kernel  # noqa: F401 — fija el event loop policy (Selector) ANTES de crear bucles
import pytest


def _reset_database(dbname: str, schemas: list[str]) -> None:
    import psycopg
    from helpers import TEST_POSTGRES_DSN

    with psycopg.connect(f"{TEST_POSTGRES_DSN} dbname={dbname}", autocommit=True) as conn, conn.cursor() as cur:
        for schema in schemas:
            cur.execute(f"DROP SCHEMA IF EXISTS {schema} CASCADE")
        cur.execute("DROP TABLE IF EXISTS public.alembic_version")


@pytest.fixture(scope="session")
def pg_available() -> None:
    import psycopg
    from helpers import TEST_POSTGRES_DSN

    try:
        with psycopg.connect(f"{TEST_POSTGRES_DSN} dbname=platform_identity", connect_timeout=3):
            pass
    except Exception as exc:
        pytest.skip(f"PostgreSQL no disponible en 127.0.0.1:5433 ({exc})")


@pytest.fixture(scope="session")
def clean_dbs(pg_available: None) -> None:
    """Elimina los schemas entre ejecuciones de la suite (migraciones los recrean)."""
    _reset_database("platform_identity", ["identity"])
    _reset_database("platform_audit", ["audit"])
    _reset_database("platform_ledger", ["ledger"])
    _reset_database("platform_accounts", ["accounts"])
    _reset_database("platform_wallet", ["wallet"])


@pytest.fixture(scope="session")
def redpanda_available() -> None:
    from helpers import redpanda_reachable

    if not redpanda_reachable():
        pytest.skip("Redpanda no disponible (REDPANDA_BOOTSTRAP_SERVERS)")
