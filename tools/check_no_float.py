"""Lint anti-float en paths de dinero (BUILD-024, ADR-0006, ADR-0018 §5, REQ-015).

Reglas (AST en Python; regex en TypeScript) — exit 1 ante cualquier violación:

1. En `services/*/src` y `packages/*/src` está prohibido `float` como literal,
   anotación o llamada `float(...)`, salvo contextos temporales (timeout,
   retry, backoff, intervalos, buckets de latencia: el identificador de
   contexto contiene una palabra clave temporal) o un archivo en
   KNOWN_EXCEPTIONS.
2. En `apps/` (TypeScript) están prohibidos `number` y literales decimales en
   identificadores de dinero (amount, balance, price, fee, pnl, margin, ...).

Uso: `uv run python tools/check_no_float.py`
"""

from __future__ import annotations

import ast
import re
import sys
from collections.abc import Iterator
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Excepciones conocidas y documentadas: deuda de decimalización en market-data
# (K-market-data §91: precios deben migrar a Decimal; ADR-0006). Se revisa al
# retomar market-data; mientras tanto el gate no puede fallar por esto.
KNOWN_EXCEPTIONS: dict[str, str] = {
    "services/market-data/src/market_data/domain/protocols.py": "ReferenceQuote.value en float (K §91 pendiente)",
    "services/market-data/src/market_data/domain/values.py": "positive_float() de proveedores (K §91 pendiente)",
    "packages/platform-contracts/src/platform_contracts/market_data.py": "OverviewQuote.value en float (K §91)",
}

# Identificadores de contexto que autorizan float (tiempos, no dinero). Se
# compara contra el nombre con "_" separado en palabras (RETRY_DELAY_SECONDS
# contiene "retry" como segmento, no como palabra con \b).
TIMING_RE = re.compile(
    r"\b(seconds?|minutes?|hours?|days?|weeks?|timeout|retry|retries|delay|"
    r"interval|backoff|sleep|duration|jitter|cooldown|elapsed|deadline|"
    r"monotonic|mono|clock|health|ttl|at|buckets?)\b",
    re.IGNORECASE,
)

MONEY_NAMES = (
    "amount",
    "balance",
    "price",
    "fee",
    "pnl",
    "margin",
    "cost",
    "total",
    "quantity",
    "notional",
    "commission",
)
TS_ANNOTATION_RE = re.compile(r"\b(?:" + "|".join(MONEY_NAMES) + r")\b\s*\??\s*:\s*number\b")
TS_LITERAL_RE = re.compile(r"\b(?:" + "|".join(MONEY_NAMES) + r")\b\s*[:=]\s*-?\d+\.\d+")


def _iter_py(base: Path) -> Iterator[Path]:
    for path in sorted(base.rglob("*.py")):
        if "__pycache__" in path.parts or "migrations" in path.parts:
            continue
        yield path


def _is_timing(name: str) -> bool:
    return bool(TIMING_RE.search(name.replace("_", " ")))


def _own_names(node: ast.AST) -> list[str]:
    """Nombres propios del nodo cuando el nodo es una definición/declaración."""
    if isinstance(node, ast.AnnAssign):
        return [ast.unparse(node.target)]
    if isinstance(node, ast.arg):
        return [node.arg]
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        return [node.name]
    if isinstance(node, ast.keyword) and node.arg:
        return [node.arg]
    return []


def _context_names(node: ast.AST, parents: dict[ast.AST, ast.AST]) -> list[str]:
    """Nombres propios + del entorno léxico (asignación, parámetro, llamada...)."""
    names = _own_names(node)
    current: ast.AST | None = node
    for _ in range(8):
        if current is None:
            break
        parent = parents.get(current)
        if parent is None:
            break
        names.extend(_own_names(parent))
        if isinstance(parent, ast.Assign):
            names.extend(ast.unparse(target) for target in parent.targets)
        elif isinstance(parent, ast.Call):
            names.append(ast.unparse(parent.func))
        elif isinstance(parent, ast.Attribute):
            names.append(parent.attr)
        elif isinstance(parent, ast.arguments):
            # Un literal en `defaults` pertenece al parámetro que lo recibe.
            positionals = parent.posonlyargs + parent.args
            if current in parent.defaults:
                index = len(positionals) - len(parent.defaults) + parent.defaults.index(current)
                if 0 <= index < len(positionals):
                    names.append(positionals[index].arg)
            for kwarg, kwdefault in zip(parent.kwonlyargs, parent.kw_defaults, strict=True):
                if kwdefault is current:
                    names.append(kwarg.arg)
        current = parent
    return names


def _allowed(node: ast.AST, parents: dict[ast.AST, ast.AST]) -> bool:
    return any(_is_timing(name) for name in _context_names(node, parents))


def _violation_kind(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, float):
        return f"literal float {node.value!r}"
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "float":
        return "llamada float(...)"
    if (
        isinstance(node, ast.AnnAssign)
        and node.annotation is not None
        and re.search(r"\bfloat\b", ast.unparse(node.annotation))
    ):
        return f"anotación float en '{ast.unparse(node.target)}'"
    if (
        isinstance(node, ast.arg)
        and node.annotation is not None
        and re.search(r"\bfloat\b", ast.unparse(node.annotation))
    ):
        return f"anotación float en parámetro '{node.arg}'"
    if (
        isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.returns is not None
        and re.search(r"\bfloat\b", ast.unparse(node.returns))
    ):
        return f"retorno float en '{node.name}'"
    return None


def _check_python() -> list[str]:
    violations: list[str] = []
    roots = sorted((ROOT / "services").iterdir()) + sorted((ROOT / "packages").iterdir())
    for svc in roots:
        src = svc / "src"
        if not src.is_dir():
            continue
        for path in _iter_py(src):
            rel = path.relative_to(ROOT).as_posix()
            if rel in KNOWN_EXCEPTIONS:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            parents: dict[ast.AST, ast.AST] = {}
            for parent_node in ast.walk(tree):
                for child in ast.iter_child_nodes(parent_node):
                    parents[child] = parent_node
            for node in ast.walk(tree):
                kind = _violation_kind(node)
                if kind and not _allowed(node, parents):
                    lineno = int(getattr(node, "lineno", 0))
                    violations.append(f"{rel}:{lineno} — {kind}")
    return violations


def _check_typescript() -> list[str]:
    violations: list[str] = []
    apps = ROOT / "apps"
    if not apps.is_dir():
        return violations
    patterns = (
        (TS_ANNOTATION_RE, "anotación number en identificador de dinero"),
        (TS_LITERAL_RE, "literal decimal en identificador de dinero"),
    )
    for extension in ("*.ts", "*.tsx"):
        for path in sorted(apps.rglob(extension)):
            if "node_modules" in path.parts:
                continue
            rel = path.relative_to(ROOT).as_posix()
            lines = path.read_text(encoding="utf-8").splitlines()
            for lineno, line in enumerate(lines, start=1):
                for regex, kind in patterns:
                    match = regex.search(line)
                    if match:
                        violations.append(f"{rel}:{lineno} — {kind} '{match.group(0).strip()}'")
    return violations


def main() -> int:
    violations = _check_python() + _check_typescript()
    if KNOWN_EXCEPTIONS:
        print("excepciones conocidas (deuda documentada):")
        for rel, reason in sorted(KNOWN_EXCEPTIONS.items()):
            print(f"  - {rel}: {reason}")
    if violations:
        print("\nVIOLACIONES ANTI-FLOAT (ADR-0006 / REQ-015):", file=sys.stderr)
        for violation in violations:
            print(f"  - {violation}", file=sys.stderr)
        return 1
    print("anti-float OK: sin float en identificadores de dinero")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
