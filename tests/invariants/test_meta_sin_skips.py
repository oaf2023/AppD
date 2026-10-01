"""Meta-test — la suite de invariantes financieros no puede contener skips.

ADR-0018 §1: I1-I5 son **bloqueantes**; ningún `skip`/`xfail` puede ocultar un
invariante roto. Analiza el AST de los ficheros de riesgo (nunca por cadenas,
para no auto-flaggearse) y falla si aparece cualquier marcador o llamada de
salto. Ejecución: `pytest tests/invariants` (se ejecuta junto al resto).
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

pytestmark = pytest.mark.invariants

REPO_ROOT = Path(__file__).resolve().parents[2]

RISK_FILES = [
    *sorted((REPO_ROOT / "tests" / "invariants").glob("*.py")),
    *[
        REPO_ROOT / "tests" / "integration" / name
        for name in (
            "test_ledger.py",
            "test_wallet.py",
            "test_accounts.py",
            "test_retention.py",
        )
    ],
    *[
        REPO_ROOT / "tests" / "unit" / name
        for name in (
            "test_ledger_postings.py",
            "test_money.py",
            "test_retention_sweep.py",
        )
    ],
]

PYTEST_SKIP_MARKS = {"skip", "skipif", "xfail"}
PYTEST_SKIP_CALLS = {"skip", "xfail", "importorskip"}
UNITTEST_SKIP_CALLS = {"skip", "skipIf", "skipUnless", "expectedFailure"}


def _chain(node: ast.AST) -> list[str]:
    """['pytest', 'mark', 'skip'] para `pytest.mark.skip`; raíz al inicio."""
    parts: list[str] = []
    current: ast.AST = node
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if isinstance(current, ast.Name):
        parts.append(current.id)
    return list(reversed(parts))


def _is_bare_skip(chain: list[str]) -> bool:
    if len(chain) < 2 or "mark" in chain:  # los `pytest.mark.*` los cubre la regla de marcador
        return False
    return (chain[0] == "pytest" and chain[-1] in PYTEST_SKIP_CALLS) or (
        chain[0] == "unittest" and chain[-1] in UNITTEST_SKIP_CALLS
    )


def _violations(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute):
            chain = _chain(node)
            is_mark_skip = (
                len(chain) >= 3 and chain[0] == "pytest" and chain[-2] == "mark" and chain[-1] in PYTEST_SKIP_MARKS
            )
            if is_mark_skip:
                found.append(f"línea {node.lineno}: marcador {'.'.join(chain)}")
            elif _is_bare_skip(chain):
                found.append(f"línea {node.lineno}: llamada {'.'.join(chain)}")
        elif isinstance(node, ast.Call):
            chain = _chain(node.func)
            if _is_bare_skip(chain):
                found.append(f"línea {node.lineno}: llamada {'.'.join(chain)}")
    return list(dict.fromkeys(found))  # Attribute + Call reportan la misma llamada una vez


def test_meta_no_hay_skips_en_la_suite_de_invariantes() -> None:
    """Fallar ante `pytest.mark.skip/skipif/xfail`, `pytest.skip/xfail/importorskip`
    o `unittest.skip` en los ficheros de riesgo (ADR-0018: sin skips en la suite)."""
    missing = [str(path.relative_to(REPO_ROOT)) for path in RISK_FILES if not path.is_file()]
    assert not missing, f"ficheros de riesgo ausentes (¿renombrados?): {missing}"

    failures: list[str] = []
    for path in RISK_FILES:
        for violation in _violations(path):
            failures.append(f"{path.relative_to(REPO_ROOT)}: {violation}")
    assert not failures, "skips prohibidos en la suite de invariantes (ADR-0018):\n" + "\n".join(failures)
