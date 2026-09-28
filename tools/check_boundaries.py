"""Lint de fronteras del monorepo (BUILD-001, ADR-0001, N-monorepo §9).

Reglas (falla con exit code 1 ante cualquier violación):
1. Un servicio solo importa su propio paquete + `platform_kernel`/`platform_contracts` +
   terceros; nunca el código fuente de otro servicio (`gateway`, `identity`, `audit`).
2. Los paquetes compartidos (`packages/*`) nunca importan código de servicios.
3. Ningún código fuente referencia la base de datos de otro servicio (`platform_<svc>`
   en strings de conexión/SQL), salvo la propia.
4. `apps/` y `tests/` son consumidores: se comprueba solo la regla 3 para ellos.

Uso: `uv run python tools/check_boundaries.py`
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SHARED_PACKAGES = {"platform_kernel", "platform_contracts"}
CONSUMER_DIRS = ("apps", "tests", "tools")


def _service_names() -> list[str]:
    return sorted(p.name for p in (ROOT / "services").iterdir() if p.is_dir())


def _iter_py(base: Path):
    for path in sorted(base.rglob("*.py")):
        if "__pycache__" in path.parts or "migrations" in path.parts:
            continue
        yield path


def _top_level_imports(path: Path) -> set[str]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except SyntaxError as exc:
        raise SystemExit(f"sintaxis inválida en {path}: {exc}") from exc
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            names.add(node.module.split(".")[0])
    return names


def _violations() -> list[str]:
    services = _service_names()
    errors: list[str] = []

    # Reglas 1 y 3: código de servicios
    for svc in services:
        src = ROOT / "services" / svc / "src"
        if not src.is_dir():
            continue
        forbidden_imports = set(services) - {svc}
        for path in _iter_py(src):
            text = path.read_text(encoding="utf-8")
            for name in sorted(_top_level_imports(path) & forbidden_imports):
                errors.append(f"{path.relative_to(ROOT)}: importa el servicio ajeno '{name}' (regla 1)")
            for other in services:
                if other == svc:
                    continue
                if f"platform_{other}" in text:
                    errors.append(
                        f"{path.relative_to(ROOT)}: referencia la base 'platform_{other}' de otro servicio (regla 3)"
                    )
            for consumer in CONSUMER_DIRS:
                if consumer in _top_level_imports(path):
                    errors.append(f"{path.relative_to(ROOT)}: importa '{consumer}' (regla 1)")

    # Regla 2: paquetes compartidos no conocen servicios
    for pkg_dir in sorted((ROOT / "packages").iterdir()):
        src = pkg_dir / "src"
        if not src.is_dir():
            continue
        for path in _iter_py(src):
            leaked = sorted(_top_level_imports(path) & set(services))
            for name in leaked:
                errors.append(f"{path.relative_to(ROOT)}: paquete compartido importa el servicio '{name}' (regla 2)")
    return errors


def main() -> int:
    errors = _violations()
    if errors:
        print("VIOLACIONES DE FRONTERA (BUILD-001):", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1
    print("fronteras OK: sin imports cruzados entre servicios ni bases ajenas")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
