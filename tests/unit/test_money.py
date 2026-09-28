"""Pruebas unitarias del manejo de dinero (ADR-0006: sin floats)."""

from __future__ import annotations

from decimal import Decimal

import pytest
from platform_kernel.money import (
    MoneyError,
    from_minor_units,
    quantize,
    sum_decimal,
    to_decimal,
    to_minor_units,
)


def test_float_esta_prohibido() -> None:
    with pytest.raises(MoneyError, match="float prohibido"):
        to_decimal(1.5)  # type: ignore[arg-type]


def test_cadena_y_decimal_se_admiten() -> None:
    assert to_decimal("10.50") == Decimal("10.50")
    assert to_decimal(7) == Decimal("7")
    assert to_decimal(Decimal("0.001")) == Decimal("0.001")


def test_cadena_invalida_lanza_error() -> None:
    with pytest.raises(MoneyError, match="inválido"):
        to_decimal("no-es-numero")


def test_quantize_round_half_up_usd() -> None:
    assert quantize("10.005", "USD") == Decimal("10.01")
    assert quantize("10.004", "USD") == Decimal("10.00")
    assert quantize("10.005", "JPY") == Decimal("10")


def test_unidades_minimas() -> None:
    assert to_minor_units("12.34", "USD") == 1234
    assert from_minor_units(1234, "USD") == Decimal("12.34")
    assert from_minor_units(1, "BTC") == Decimal("0.00000001")


def test_unidad_desconocida() -> None:
    with pytest.raises(MoneyError, match="unidad mínima desconocida"):
        to_minor_units("1", "XYZCOIN")


def test_suma_decimal_sin_floats() -> None:
    assert sum_decimal(["1.10", 2, Decimal("3.30")]) == Decimal("6.40")
