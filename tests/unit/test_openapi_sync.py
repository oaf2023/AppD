"""BUILD-016 / ADR-0004 — gate de deriva del OpenAPI canónico.

Falla si `packages/platform-contracts/openapi/<svc>.yaml` o `services/<svc>/openapi.yaml`
dejan de reflejar el código, o si el spec no es OpenAPI válido.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

import yaml
from openapi_spec_validator import validate as validate_spec

_ROOT = Path(__file__).resolve().parents[2]
_SPEC = importlib.util.spec_from_file_location("export_openapi", _ROOT / "tools" / "export_openapi.py")
assert _SPEC is not None and _SPEC.loader is not None
_EXPORT = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_EXPORT)


def _expected(service: str) -> str:
    return _EXPORT.render(_EXPORT.build_spec(service))


def test_specs_validos_y_sin_deriva() -> None:
    for service in _EXPORT.SERVICES:
        expected = _expected(service)
        spec: dict[str, Any] = yaml.safe_load(expected)
        validate_spec(spec)
        for path in _EXPORT.targets(service):
            assert path.is_file(), f" falta {path}"
            assert path.read_text(encoding="utf-8").replace("\r\n", "\n") == expected, (
                f"{path.relative_to(_ROOT)} difiere del código — ejecuta `uv run python tools/export_openapi.py`"
            )


def test_info_y_versionado_presentes() -> None:
    for service in _EXPORT.SERVICES:
        spec: dict[str, Any] = yaml.safe_load(_expected(service))
        assert spec["openapi"].startswith("3.1"), f"{service}: OpenAPI 3.1 requerido (ADR-0004)"
        assert spec["info"]["title"] and spec["info"]["version"], f"{service}: info incompleto"
