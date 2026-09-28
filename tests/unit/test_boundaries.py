"""BUILD-001 — el CI falla ante una violación de frontera del monorepo."""

from __future__ import annotations

import importlib.util
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_SPEC = importlib.util.spec_from_file_location("check_boundaries", _ROOT / "tools" / "check_boundaries.py")
assert _SPEC is not None and _SPEC.loader is not None
_BOUNDARIES = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_BOUNDARIES)


def test_sin_imports_cross_service() -> None:
    assert _BOUNDARIES._violations() == []


def test_detector_detecta_violacion(tmp_path: Path) -> None:
    """El propio detector falla si un servicio importa a otro (auto-test del linter)."""
    probe = _ROOT / "services" / "identity" / "src" / "identity" / "_probe_tmp.py"
    probe.write_text("import audit\n", encoding="utf-8")
    try:
        assert _BOUNDARIES._violations() != []
    finally:
        probe.unlink()
