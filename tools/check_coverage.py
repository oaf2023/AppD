"""Gates de cobertura de Fase 2 (BUILD-024, ADR-0018, REQ-015/REQ-074).

Lee `coverage.json` (raíz del repo) y falla con exit 1 si algún umbral no se
alcanza. Umbrales:

  - services/ledger: >= 90% líneas y >= 85% ramas
  - services/wallet: >= 85% líneas y >= 85% ramas
  - total del repo:  >= 80% líneas (sin umbral de ramas)

Uso:
  uv run pytest --cov --cov-report=json
  uv run python tools/check_coverage.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent

# (prefijo de archivo o None para el total, nombre, min_líneas%, min_ramas%|None)
GATES: tuple[tuple[str | None, str, float, float | None], ...] = (
    ("services/ledger/", "ledger", 90.0, 85.0),
    ("services/wallet/", "wallet", 85.0, 85.0),
    (None, "total", 80.0, None),
)


def _load(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise SystemExit(f"no existe {path.name}; genera el reporte antes: uv run pytest --cov --cov-report=json")
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return data


def _aggregate(files: dict[str, Any], prefix: str | None) -> tuple[int, int, int, int]:
    """Devuelve (sentencias, cubiertas, ramas, ramas cubiertas) del subárbol."""
    total = covered = branches = branches_covered = 0
    for name, data in files.items():
        norm = name.replace("\\", "/")
        if prefix and not norm.startswith(prefix):
            continue
        summary = data["summary"]
        covered += summary.get("covered_lines", 0)
        total += summary.get("num_statements", 0)
        branches_covered += summary.get("covered_branches", 0)
        branches += summary.get("num_branches", 0)
    return total, covered, branches, branches_covered


def _pct(covered: int, total: int) -> float:
    return 100.0 * covered / total if total else 0.0


def _detail(files: dict[str, Any], prefix: str) -> list[str]:
    """Archivos del subárbol con cobertura incompleta (para depurar)."""
    lines: list[str] = []
    for name, data in sorted(files.items()):
        norm = name.replace("\\", "/")
        if not norm.startswith(prefix):
            continue
        summary = data["summary"]
        total = summary.get("num_statements", 0)
        covered = summary.get("covered_lines", 0)
        branches = summary.get("num_branches", 0)
        branches_covered = summary.get("covered_branches", 0)
        if total and (covered < total or branches_covered < branches):
            lines.append(
                f"    {norm[len('services/') :] if norm.startswith('services/') else norm}: "
                f"líneas {covered}/{total}, ramas {branches_covered}/{branches}"
            )
    return lines


def main() -> int:
    data = _load(ROOT / "coverage.json")
    files = data["files"]

    failures: list[str] = []
    print("gates de cobertura (BUILD-024):")
    for prefix, name, min_lines, min_branches in GATES:
        total, covered, branches, branches_covered = _aggregate(files, prefix)
        lines_pct = _pct(covered, total)
        branches_pct = _pct(branches_covered, branches)
        branch_text = (
            f" ramas {branches_pct:5.1f}% ({branches_covered}/{branches})"
            if min_branches is not None
            else f" ramas {branches_pct:5.1f}% ({branches_covered}/{branches}, sin umbral)"
        )
        print(f"  {name:7s} líneas {lines_pct:5.1f}% ({covered}/{total}){branch_text}")
        gate_failed = False
        if lines_pct < min_lines:
            failures.append(f"{name}: líneas {lines_pct:.1f}% < {min_lines:.0f}%")
            gate_failed = True
        if min_branches is not None and branches and branches_pct < min_branches:
            failures.append(f"{name}: ramas {branches_pct:.1f}% < {min_branches:.0f}%")
            gate_failed = True
        if prefix and gate_failed:
            for line in _detail(files, prefix):
                print(line)

    if failures:
        print("\nGATE DE COBERTURA FALLIDO:", file=sys.stderr)
        for failure in failures:
            print(f"  - {failure}", file=sys.stderr)
        return 1
    print("cobertura OK: todos los umbrales alcanzados")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
