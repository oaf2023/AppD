"""Exporta y valida el OpenAPI canónico por servicio (ADR-0004, BUILD-016).

- Fuente: la app FastAPI de cada servicio (`app.openapi()`).
- Artefactos: `packages/platform-contracts/openapi/<servicio>.yaml` (registro canónico)
  y `services/<servicio>/openapi.yaml` (export generado). El CI exige igualdad entre
  ambos y con el código (gate de deriva).

Uso:
    uv run python tools/export_openapi.py            # exporta (reescribe)
    uv run python tools/export_openapi.py --check    # falla si hay deriva (CI)
"""

from __future__ import annotations

import argparse
import importlib
import sys
from pathlib import Path
from typing import Any

import yaml
from openapi_spec_validator import validate as validate_spec

ROOT = Path(__file__).resolve().parent.parent
CANONICAL_DIR = ROOT / "packages" / "platform-contracts" / "openapi"
SERVICES = ("gateway", "identity", "audit", "market-data", "ledger", "accounts")
# El nombre del directorio del servicio puede diferir del nombre del paquete Python
MODULES = {"market-data": "market_data"}


def build_spec(service: str) -> dict[str, Any]:
    module = importlib.import_module(f"{MODULES.get(service, service)}.main")
    app = module.app
    spec: dict[str, Any] = app.openapi()
    validate_spec(spec)
    return spec


def render(spec: dict[str, Any]) -> str:
    return yaml.safe_dump(spec, sort_keys=True, allow_unicode=True)


def targets(service: str) -> tuple[Path, Path]:
    return CANONICAL_DIR / f"{service}.yaml", ROOT / "services" / service / "openapi.yaml"


def export() -> int:
    CANONICAL_DIR.mkdir(parents=True, exist_ok=True)
    for service in SERVICES:
        content = render(build_spec(service))
        for path in targets(service):
            path.write_text(content, encoding="utf-8", newline="\n")
        print(f"exportado {service}: {len(content)} bytes")
    return 0


def check() -> int:
    failures: list[str] = []
    for service in SERVICES:
        expected = render(build_spec(service))
        for path in targets(service):
            if not path.is_file():
                failures.append(f"{path.relative_to(ROOT)} no existe")
                continue
            actual = path.read_text(encoding="utf-8").replace("\r\n", "\n")
            if actual != expected:
                failures.append(
                    f"{path.relative_to(ROOT)} difiere del código — ejecuta "
                    f"`uv run python tools/export_openapi.py` y commitea el resultado"
                )
    if failures:
        print("DERIVA OpenAPI (BUILD-016/ADR-0004):", file=sys.stderr)
        for failure in failures:
            print(f"  - {failure}", file=sys.stderr)
        return 1
    print("openapi OK: specs canónicos y exports iguales al código")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="solo verifica (CI)")
    args = parser.parse_args()
    return check() if args.check else export()


if __name__ == "__main__":
    raise SystemExit(main())
