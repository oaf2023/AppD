"""Pruebas unitarias de la localización de `alembic.ini` (ledger y wallet).

`_find_ini` (L §run_migrations / W §run_migrations): variable de entorno
`ALEMBIC_INI`, raíz del servicio en dev, cwd en imagen, fallback a la raíz.
"""

from __future__ import annotations

import pytest
from ledger import migrate as ledger_migrate
from wallet import migrate as wallet_migrate

MODULOS = [ledger_migrate, wallet_migrate]
IDS = ["ledger", "wallet"]


@pytest.mark.parametrize("module", MODULOS, ids=IDS)
def test_find_ini_prefiere_la_variable_de_entorno(module, monkeypatch, tmp_path) -> None:
    destino = tmp_path / "custom" / "alembic.ini"
    monkeypatch.setenv("ALEMBIC_INI", str(destino))
    assert module._find_ini() == destino


@pytest.mark.parametrize("module", MODULOS, ids=IDS)
def test_find_ini_busca_en_la_raiz_del_servicio_y_luego_en_el_cwd(module, monkeypatch, tmp_path) -> None:
    monkeypatch.delenv("ALEMBIC_INI", raising=False)
    raiz = tmp_path / "servicio"
    monkeypatch.setattr(module, "_SERVICE_ROOT", raiz)
    monkeypatch.chdir(tmp_path)
    assert module._find_ini() == raiz / "alembic.ini"
