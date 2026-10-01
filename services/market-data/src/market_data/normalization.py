"""normalización — validación de ticks crudos al contrato canónico (K §4.4, BUILD-027).

Reglas de entrada (nunca se confía al feed, principio 6 de AGENTS.md):
- precio y tamaño solo `Decimal`/`int`/`str` — **`float` rechazado** (ADR-0006);
- precio > 0, tamaño >= 0, `side` ∈ buy/sell/na;
- `ts`/`recv_ts` con zona horaria; `ts` en el futuro más allá del skew
  crítico de 2 s (K §4.4 relojes: warning 500 ms, crítico 2 s) ⇒ descarte;
- símbolo con formato canónico (`EUR/USD`, `BTC/USD`).

Un raw inválido ⇒ `CanonicalDataError` (cuarentena en el ingestor: se cuenta
como descartado y jamás se "corrige" el dato para encajar).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation

from market_data.domain.models import TICK_SIDES, CanonicalDataError, Tick

#: Skew máximo permitido del timestamp del productor respecto al reloj receptor.
FUTURE_SKEW = timedelta(seconds=2)

SYMBOL_RE = re.compile(r"^[A-Z0-9]{2,8}(/[A-Z0-9]{2,8})?$")

#: Tipos de precio admitidos al normalizar (el `float` queda fuera por diseño).
DecimalLike = Decimal | int | str


@dataclass(frozen=True, slots=True)
class RawTick:
    """Tick crudo llegado del pipeline de ingest (antes de validación canónica)."""

    symbol: str
    price: object  # Decimal | int | str; un float debe rechazarse (ADR-0006)
    side: str
    size: object | None
    ts: datetime
    source: str
    simulated: bool
    provider_seq: int | None = None
    recv_ts: datetime | None = None


def _to_decimal(name: str, value: object) -> Decimal:
    if isinstance(value, bool):
        raise CanonicalDataError(f"{name}: bool no es un valor numérico de mercado")
    if isinstance(value, float):
        raise CanonicalDataError(f"{name}: float prohibido (ADR-0006); recibe Decimal|str|int")
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, str):
        try:
            return Decimal(value)
        except InvalidOperation as exc:
            raise CanonicalDataError(f"{name}: cadena decimal inválida {value!r}") from exc
    raise CanonicalDataError(f"{name}: tipo no soportado {type(value).__name__}")


def normalize_tick(raw: RawTick, *, now: datetime) -> Tick:
    """Convierte un `RawTick` en `Tick` canónico o lanza `CanonicalDataError`."""
    if not SYMBOL_RE.match(raw.symbol or ""):
        raise CanonicalDataError(f"symbol: formato inválido {raw.symbol!r}")
    if not raw.source:
        raise CanonicalDataError("source: no puede estar vacío")
    if raw.side not in TICK_SIDES:
        raise CanonicalDataError(f"side: valor desconocido {raw.side!r}")
    if raw.ts.utcoffset() is None:
        raise CanonicalDataError("ts: debe ser un timestamp con zona horaria (UTC)")
    if raw.ts > now + FUTURE_SKEW:
        raise CanonicalDataError(f"ts: en el futuro (skew > {FUTURE_SKEW}); posible reloj de proveedor")
    recv_ts = raw.recv_ts if raw.recv_ts is not None else now
    if recv_ts.utcoffset() is None:
        raise CanonicalDataError("recv_ts: debe ser un timestamp con zona horaria (UTC)")
    size = None if raw.size is None else _to_decimal("size", raw.size)
    return Tick(
        symbol=raw.symbol,
        price=_to_decimal("price", raw.price),
        side=raw.side,  # type: ignore[arg-type]  # ya validado contra TICK_SIDES
        size=size,
        ts=raw.ts,
        recv_ts=recv_ts,
        source=raw.source,
        simulated=raw.simulated,
        provider_seq=raw.provider_seq,
    )


__all__ = ["FUTURE_SKEW", "SYMBOL_RE", "RawTick", "normalize_tick"]
