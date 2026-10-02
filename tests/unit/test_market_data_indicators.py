"""Pruebas unitarias de indicadores (BUILD-031, C-gap: SMA/EMA/RSI/MACD).

Casos dorados con aritmética `Decimal` exacta calculada a mano y verificada
contra un oráculo float independiente (fórmulas desde cero, tolerancia 1e-9);
sin vendor y sin `float` en el código de producción.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from market_data.indicators import ema, macd, rsi, sma

D = Decimal

# serie no aritmética (evita que SMA y EMA colusionen en la comparación)
SERIES = [D(x) for x in (2, 4, 6, 3, 9, 5, 7, 10, 4, 8, 6, 12)]


def test_sma_dorado_y_propiedades() -> None:
    values = [D(x) for x in range(1, 11)]  # 1..10
    assert sma(values, 3) == [None, None, D(2), D(3), D(4), D(5), D(6), D(7), D(8), D(9)]
    # period 1 ⇒ identidad; period > len ⇒ todo en calentamiento
    assert sma(values, 1) == values
    assert sma(values, 13) == [None] * 10
    assert sma([], 3) == []
    # ventana deslizante: la media de la cola entera coincide con el último valor
    tail_mean = sma(SERIES, 12)[-1]
    assert tail_mean == sum(SERIES, start=D(0)) / 12


def test_ema_dorado_semilla_sma() -> None:
    # k = 2/(3+1) = 0.5 exacto; semilla SMA de los 3 primeros
    assert ema([D(1), D(2), D(3), D(4), D(5), D(6), D(7), D(8), D(9), D(10)], 3) == [
        None,
        None,
        D(2),
        D(3),
        D(4),
        D(5),
        D(6),
        D(7),
        D(8),
        D(9),
    ]
    # serie no aritmética: [6,3,9] ⇒ semilla 6; luego 1*0.5+6*0.5=3.5; 5*0.5+3.5*0.5=4.25
    assert ema([D(6), D(3), D(9), D(1), D(5)], 3) == [None, None, D(6), D("3.5"), D("4.25")]
    # k = 2/(4+1) = 0.4 exacto; semilla (4+8+2+6)/4 = 5
    assert ema([D(4), D(8), D(2), D(6), D(10), D(5)], 4) == [None, None, None, D(5), D(7), D("6.2")]
    assert ema([], 3) == []


def test_rsi_dorado_wilder() -> None:
    # cambios +3,-1,+2: avg_gain=1.5, avg_loss=0.5 ⇒ RS=3 ⇒ RSI=75
    # siguiente cambio +2: (1.5+2)/2=1.75, 0.5/2=0.25 ⇒ RS=7 ⇒ 100-100/8=87.5
    assert rsi([D(10), D(13), D(12), D(14)], 2) == [None, None, D(75), D("87.5")]
    # sin pérdidas ⇒ 100 (suavizado de Wilder: (1+1)/2=1)
    assert rsi([D(10), D(11), D(12), D(13)], 2) == [None, None, D(100), D(100)]
    # solo caídas: avg_gain=0 ⇒ RS=0 ⇒ 100-100/1 = 0
    assert rsi([D(12), D(11), D(10)], 2) == [None, None, D(0)]
    # por defecto period=14: una serie corta queda toda en calentamiento
    assert rsi(SERIES) == [None] * 12
    assert rsi([], 14) == []


def test_macd_dorado_linea_senal_histograma() -> None:
    # fast=3 (k=0.5), slow=4 (k=0.4), signal=3 (k=0.5): todos los pasos terminan en decimal finito
    result = macd(SERIES, fast=3, slow=4, signal=3)
    assert result.line == [
        None,
        None,
        None,
        D("-0.25"),
        D("0.400"),
        D("0.1150"),
        D("0.20650"),
        D("0.492650"),
        D("-0.1200350"),
        D("0.12016650"),
        D("-0.031806350"),
        D("0.5289630650"),
    ]
    assert result.signal == [
        None,
        None,
        None,
        None,
        None,
        D("0.08833333333333333333333333333"),
        D("0.1474166666666666666666666667"),
        D("0.3200333333333333333333333334"),
        D("0.0999991666666666666666666667"),
        D("0.1100828333333333333333333334"),
        D("0.03913824166666666666666666670"),
        D("0.2840506533333333333333333334"),
    ]
    assert result.histogram == [
        None,
        None,
        None,
        None,
        None,
        D("0.02666666666666666666666666667"),
        D("0.0590833333333333333333333333"),
        D("0.1726166666666666666666666666"),
        D("-0.2200341666666666666666666667"),
        D("0.0100836666666666666666666666"),
        D("-0.07094459166666666666666666670"),
        D("0.2449124116666666666666666666"),
    ]
    # histograma = linea - senal donde ambos existen (invariante estructural)
    for m, s, h in zip(result.line, result.signal, result.histogram, strict=True):
        if h is not None:
            assert m is not None and s is not None and h == m - s


def test_macd_por_defecto_y_ventanas_de_calentamiento() -> None:
    # (12, 26, 9) con 12 valores: la línea aún no nace (slow > len)
    cold = macd(SERIES)
    assert cold.line == [None] * 12
    assert cold.signal == [None] * 12
    assert cold.histogram == [None] * 12
    assert macd([]) == macd([])  # estructura vacía comparable
    assert macd([]).line == []

    # con 40 valores la línea nace en el índice 25 (slow-1) y la señal 8 después
    long_series = [D(x) for x in range(1, 41)]
    full = macd(long_series)
    assert full.line[:25] == [None] * 25
    assert full.line[25] is not None
    assert full.signal[:33] == [None] * 33  # 25 + (signal-1)
    assert full.signal[33] is not None
    assert full.histogram[33] == full.line[33] - full.signal[33]


def test_validacion_de_entradas() -> None:
    with pytest.raises(ValueError, match="sma"):
        sma(SERIES, 0)
    with pytest.raises(ValueError, match="ema"):
        ema(SERIES, -1)
    with pytest.raises(ValueError, match="fast < slow"):
        macd(SERIES, fast=9, slow=4, signal=3)
    with pytest.raises(ValueError, match="signal"):
        macd(SERIES, fast=3, slow=4, signal=0)
    with pytest.raises(TypeError, match=r"values\[1\]: se exige Decimal"):
        sma([D(1), 2.5, D(3)], 2)  # type: ignore[list-item]
    with pytest.raises(TypeError, match="se exige Decimal"):
        rsi([float(x) for x in range(1, 16)], 14)  # type: ignore[list-item]
