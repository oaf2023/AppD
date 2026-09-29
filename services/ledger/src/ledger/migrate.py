"""migrate — ejecución programática de las migraciones Alembic del Ledger Service."""

from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger("ledger.migrate")

_SERVICE_ROOT = Path(__file__).resolve().parents[2]


def _find_ini() -> Path:
    """Localiza alembic.ini: env explícita, raíz del servicio (dev) o cwd (imagen)."""
    env_path = os.environ.get("ALEMBIC_INI")
    if env_path:
        return Path(env_path)
    for candidate in (_SERVICE_ROOT / "alembic.ini", Path.cwd() / "alembic.ini"):
        if candidate.is_file():
            return candidate
    return _SERVICE_ROOT / "alembic.ini"


_MIGRATIONS_INI = _find_ini()


def run_migrations(database_url: str) -> None:
    from alembic import command
    from alembic.config import Config

    cfg = Config(str(_MIGRATIONS_INI))
    cfg.set_main_option("sqlalchemy.url", database_url)
    command.upgrade(cfg, "head")
    logger.info("migraciones aplicadas", extra={"extra_fields": {"service": "ledger"}})


__all__ = ["run_migrations"]
