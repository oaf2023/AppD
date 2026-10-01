"""conftest de la suite de invariantes financieros (ADR-0018, BUILD-024).

Perfiles de hypothesis (CI determinista; `HYPOTHESIS_PROFILE=nightly` amplía los
ejemplos), app `ledger` con lifespan real y esquema `wallet` disponible para
verificar la proyección (I2). El entorno de test ya está fijado por
`tests/conftest.py` (importa `helpers` antes de cargar servicios).
"""

from __future__ import annotations

import os

import pytest
from helpers import lifespan_client
from hypothesis import HealthCheck, settings

settings.register_profile(
    "ci",
    max_examples=int(os.environ.get("HYPOTHESIS_MAX_EXAMPLES", "30")),
    derandomize=True,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture, HealthCheck.too_slow],
)
settings.register_profile(
    "nightly",
    max_examples=int(os.environ.get("HYPOTHESIS_MAX_EXAMPLES", "200")),
    derandomize=False,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture, HealthCheck.too_slow],
)
settings.load_profile(os.environ.get("HYPOTHESIS_PROFILE", "ci"))


# --------------------------------------------------------------------------- fixtures


@pytest.fixture
async def ledger_client(clean_dbs: None):  # type: ignore[no-untyped-def]
    """App ledger real (migraciones + lifespan) con relay outbox deshabilitado.

    El relay real necesita Redpanda; aquí se verifica la fila del outbox atómica.
    Se fija SOLO durante este fixture (patrón de tests/integration/test_ledger.py).
    """
    from ledger.config import get_ledger_settings
    from ledger.db import reset_engine

    previous = os.environ.get("OUTBOX_RELAY_ENABLED")
    os.environ["OUTBOX_RELAY_ENABLED"] = "false"
    get_ledger_settings.cache_clear()
    reset_engine()

    from ledger.main import create_app

    try:
        async with lifespan_client(create_app()) as client:
            yield client
    finally:
        if previous is None:
            os.environ.pop("OUTBOX_RELAY_ENABLED", None)
        else:
            os.environ["OUTBOX_RELAY_ENABLED"] = previous
        get_ledger_settings.cache_clear()
        reset_engine()


@pytest.fixture(scope="session")
def wallet_ready(clean_dbs: None):  # type: ignore[no-untyped-def]
    """Aplica las migraciones de wallet (idempotente) y libera el motor al terminar."""
    from wallet.config import get_wallet_settings
    from wallet.db import reset_engine
    from wallet.migrate import run_migrations

    run_migrations(get_wallet_settings().wallet_database_url)
    yield
    reset_engine()
