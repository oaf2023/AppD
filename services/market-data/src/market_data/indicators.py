"""indicators — indicadores técnicos puros sobre `Decimal` (BUILD-031, K §0/C-gap).

SMA, EMA (semilla = SMA de la ventana inicial), RSI de Wilder (suavizado
`(prev*(period-1) + actual)/period`) y MACD (EMA rapida - EMA lenta, senal =
EMA de la linea MACD, histograma = MACD - senal). Sin vendor, sin `float` y
sin redondeo propio: la aritmetica es `Decimal` y la division sigue el
contexto decimal global (ADR-0006).

Cada serie devuelta está **alineada al input** con `None` durante el
calentamiento. Módulo puro sin I/O ni endpoints: BUILD-031 no expone REST;
los llamadores (charting/análisis) alimentan la serie desde los cierres de
`candles`.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal

__all__ = ["Macd", "ema", "macd", "rsi", "sma"]


def _require_period(name: str, period: int) -> None:
    if isinstance(period, bool) or not isinstance(period, int) or period < 1:
        raise ValueError(f"{name}: period debe ser un entero >= 1; llegó {period!r}")


def _require_decimals(values: Sequence[Decimal]) -> None:
    for index, value in enumerate(values):
        if not isinstance(value, Decimal) or isinstance(value, bool):
            raise TypeError(f"values[{index}]: se exige Decimal (ADR-0006); llegó {type(value).__name__}")


def sma(values: Sequence[Decimal], period: int) -> list[Decimal | None]:
    """Media móvil simple de `period` valores, alineada al input (`None` en calentamiento)."""
    _require_period("sma", period)
    _require_decimals(values)
    out: list[Decimal | None] = [None] * len(values)
    window = Decimal(0)
    for index, value in enumerate(values):
        window += value
        if index >= period:
            window -= values[index - period]
        if index >= period - 1:
            out[index] = window / period
    return out


def ema(values: Sequence[Decimal], period: int) -> list[Decimal | None]:
    """Media móvil exponencial con semilla `SMA(values[:period])` (convención de ventana)."""
    _require_period("ema", period)
    _require_decimals(values)
    out: list[Decimal | None] = [None] * len(values)
    if len(values) < period:
        return out
    k = Decimal(2) / Decimal(period + 1)
    one_minus_k = Decimal(1) - k
    previous = sum(values[:period], start=Decimal(0)) / period
    out[period - 1] = previous
    for index in range(period, len(values)):
        previous = values[index] * k + previous * one_minus_k
        out[index] = previous
    return out


def _rsi_value(avg_gain: Decimal, avg_loss: Decimal) -> Decimal:
    # sin pérdidas (incl. plano total) ⇒ 100 por convención de Wilder
    if avg_loss == 0:
        return Decimal(100)
    relative_strength = avg_gain / avg_loss
    return Decimal(100) - Decimal(100) / (Decimal(1) + relative_strength)


def rsi(values: Sequence[Decimal], period: int = 14) -> list[Decimal | None]:
    """RSI de Wilder: suavizado `(prev*(period-1) + cambio)/period`; primera señal en `period`.

    Cambios positivos alimentan el promedio de ganancias y los negativos el de
    pérdidas (en valor absoluto). `avg_loss == 0` ⇒ 100 (sin pérdidas).
    """
    _require_period("rsi", period)
    _require_decimals(values)
    out: list[Decimal | None] = [None] * len(values)
    if len(values) <= period:
        return out
    gains = Decimal(0)
    losses = Decimal(0)
    for index in range(1, period + 1):
        change = values[index] - values[index - 1]
        if change > 0:
            gains += change
        elif change < 0:
            losses -= change
    avg_gain = gains / period
    avg_loss = losses / period
    out[period] = _rsi_value(avg_gain, avg_loss)
    for index in range(period + 1, len(values)):
        change = values[index] - values[index - 1]
        gain = change if change > 0 else Decimal(0)
        loss = -change if change < 0 else Decimal(0)
        avg_gain = (avg_gain * (period - 1) + gain) / period
        avg_loss = (avg_loss * (period - 1) + loss) / period
        out[index] = _rsi_value(avg_gain, avg_loss)
    return out


@dataclass(frozen=True)
class Macd:
    """Series MACD alineadas al input: línea, señal e histograma (`None` en calentamiento)."""

    line: list[Decimal | None]
    signal: list[Decimal | None]
    histogram: list[Decimal | None]


def macd(
    values: Sequence[Decimal],
    *,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> Macd:
    """MACD: `EMA(fast) - EMA(slow)`, senal `EMA(signal)` sobre la cola no nula de la linea."""
    _require_period("macd:fast", fast)
    _require_period("macd:slow", slow)
    _require_period("macd:signal", signal)
    if fast >= slow:
        raise ValueError(f"macd: fast < slow; llegó fast={fast}, slow={slow}")
    _require_decimals(values)
    empty = Macd(line=[], signal=[], histogram=[])
    if not values:
        return empty
    fast_line = ema(values, fast)
    slow_line = ema(values, slow)
    line: list[Decimal | None] = [
        f - s if f is not None and s is not None else None for f, s in zip(fast_line, slow_line, strict=True)
    ]
    first = next((index for index, value in enumerate(line) if value is not None), None)
    if first is None:
        return Macd(line=line, signal=[None] * len(values), histogram=[None] * len(values))
    tail = [value for value in line[first:] if value is not None]
    tail_signal = ema(tail, signal)
    warmup: list[Decimal | None] = [None] * first
    signal_line: list[Decimal | None] = warmup + tail_signal
    histogram = [m - s if m is not None and s is not None else None for m, s in zip(line, signal_line, strict=True)]
    return Macd(line=line, signal=signal_line, histogram=histogram)
