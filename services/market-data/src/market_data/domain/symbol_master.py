"""symbol_master — lógica del catálogo versionado (K §2/§4, REQ-025/REQ-099, BUILD-028).

- `spec_asof`: qué versión de spec regía en un instante (REQ-025: cambiar la
  spec cierra la versión anterior con `valid_to` y **no** afecta datos/ticks
  ya persistidos — ellos conservan su `ts` y se consultan con la spec de su
  momento).
- `compute_market_status`: estado del mercado (`open`/`closed`/`halted`) desde
  sesiones + suspensión + festivos. Prioridad: **suspensión > festivo >
  horario** (K §2: `halted` ≠ `closed`). Horarios en UTC (ventanas declaradas
  con `timezone` IANA; el seed demo usa `Etc/UTC`, conversión identidad — el
  desfase de horario de verano llega con calendarios reales).
- `validate_order`: rechazo tipado de una orden fuera de spec o con mercado
  no abierto (W BUILD-028, REQ-025/REQ-099) — el consumidor definitivo es el
  OMS de Fase 4; aquí vive la regla para que sea testeable hoy.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from market_data.domain.errors import MarketClosedError, MarketHaltedError, SpecViolationError
from market_data.domain.models import (
    CanonicalDataError,
    InstrumentSpec,
    MarketStatus,
    Suspension,
    TradingSession,
)

#: Días hacia adelante para calcular `next_open` (cubre el fin de semana largo
#: del forex: cierre viernes → apertura domingo, < 4 días; 8 es un margen).
OPEN_SCAN_DAYS = 8


def spec_asof(specs: Sequence[InstrumentSpec], now: datetime) -> InstrumentSpec | None:
    """Versión vigente de `specs` en el instante `now` (REQ-025)."""
    if now.tzinfo is None:
        raise CanonicalDataError("now: debe ser un timestamp con zona horaria (UTC)")
    candidates = [spec for spec in specs if spec.valid_from <= now and (spec.valid_to is None or spec.valid_to > now)]
    if not candidates:
        return None
    return max(candidates, key=lambda spec: (spec.valid_from, spec.version))


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise CanonicalDataError("timestamp: debe tener zona horaria (UTC)")
    return value.astimezone(UTC)


def _window_containing(session: TradingSession, now: datetime) -> tuple[datetime, datetime] | None:
    """Ventana de `session` que contiene a `now` (UTC), si existe.

    La ventana puede haber empezado ayer (cruce de medianoche) o hoy; ver
    semántica de ventanas en `TradingSession`.
    """
    day = now.date()
    for start_day in (day - timedelta(days=1), day):
        if start_day.weekday() != session.weekday:
            continue
        start_dt = datetime.combine(start_day, session.open_utc, tzinfo=UTC)
        if session.open_utc == session.close_utc:
            end_dt = start_dt + timedelta(days=1)
        elif session.open_utc < session.close_utc:
            end_dt = datetime.combine(start_day, session.close_utc, tzinfo=UTC)
        else:
            end_dt = datetime.combine(start_day + timedelta(days=1), session.close_utc, tzinfo=UTC)
        if start_dt <= now < end_dt:
            return start_dt, end_dt
    return None


def _next_window_start(
    sessions: Sequence[TradingSession],
    after: datetime,
    holidays: Mapping[date, str],
) -> datetime | None:
    """Próximo inicio de sesión estrictamente posterior a `after`, sin festivos."""
    best: datetime | None = None
    for offset in range(OPEN_SCAN_DAYS + 1):
        day = after.date() + timedelta(days=offset)
        if day in holidays:
            continue
        for session in sessions:
            if session.weekday != day.weekday():
                continue
            start = datetime.combine(day, session.open_utc, tzinfo=UTC)
            if start > after and (best is None or start < best):
                best = start
    return best


def compute_market_status(
    *,
    symbol: str,
    sessions: Sequence[TradingSession],
    suspension: Suspension | None,
    holidays: Mapping[date, str],
    source: str,
    simulated: bool,
    now: datetime,
) -> MarketStatus:
    """Estado del mercado de `symbol` en `now` (REQ-099, K §2).

    - suspensión vigente ⇒ `halted` (`reason=suspended:<code>`);
    - festivo del día UTC ⇒ `closed` (`reason=holiday:<label>`);
    - dentro de una ventana de sesión ⇒ `open` (`next_close` = fin de ventana);
    - en otro caso ⇒ `closed` (`reason=out_of_hours`, `next_open` calculado).
    """
    now_utc = _as_utc(now)
    if (
        suspension is not None
        and suspension.starts_at <= now_utc
        and (suspension.ends_at is None or suspension.ends_at > now_utc)
    ):
        return MarketStatus(
            symbol=symbol,
            status="halted",
            reason=f"suspended:{suspension.code}",
            as_of=now_utc,
            source=source,
            simulated=simulated,
            next_open=_next_window_start(sessions, now_utc, holidays),
            next_close=None,
        )
    today = now_utc.date()
    if today in holidays:
        return MarketStatus(
            symbol=symbol,
            status="closed",
            reason=f"holiday:{holidays[today]}",
            as_of=now_utc,
            source=source,
            simulated=simulated,
            next_open=_next_window_start(sessions, now_utc, holidays),
            next_close=None,
        )
    for session in sessions:
        window = _window_containing(session, now_utc)
        if window is not None:
            _start, end = window
            return MarketStatus(
                symbol=symbol,
                status="open",
                reason="session",
                as_of=now_utc,
                source=source,
                simulated=simulated,
                next_open=None,
                next_close=end,
            )
    return MarketStatus(
        symbol=symbol,
        status="closed",
        reason="out_of_hours",
        as_of=now_utc,
        source=source,
        simulated=simulated,
        next_open=_next_window_start(sessions, now_utc, holidays),
        next_close=None,
    )


def validate_order(
    *,
    spec: InstrumentSpec,
    status: MarketStatus,
    price: Decimal,
    volume: Decimal,
    symbol: str | None = None,
) -> None:
    """Rechazo tipado de orden fuera de spec o con mercado no abierto.

    Orden de comprobación: estado del mercado primero (`MARKET_CLOSED`/
    `MARKET_HALTED`, REQ-099) y después la spec (`TICK_SIZE`, `VOLUME_RANGE`,
    `VOLUME_STEP`, `PRICE_POSITIVE` — REQ-025). `price`/`volume` deben ser
    `Decimal` (ADR-0006): un float es violación del contrato canónico, no de
    la spec.
    """
    sym = symbol or spec.symbol
    if status.status == "halted":
        raise MarketHaltedError(f"{sym}: símbolo suspendido ({status.reason})", symbol=sym)
    if status.status == "closed":
        raise MarketClosedError(f"{sym}: mercado cerrado ({status.reason})", symbol=sym)
    if not isinstance(price, Decimal):
        raise CanonicalDataError(f"price: se exige Decimal (ADR-0006); llegó {type(price).__name__}")
    if not isinstance(volume, Decimal):
        raise CanonicalDataError(f"volume: se exige Decimal (ADR-0006); llegó {type(volume).__name__}")
    if price <= 0:
        raise SpecViolationError(f"price: debe ser > 0; llegó {price}", code="PRICE_POSITIVE", symbol=sym)
    if price % spec.tick_size != 0:
        raise SpecViolationError(
            f"price {price} no es múltiplo de tick_size {spec.tick_size}",
            code="TICK_SIZE",
            symbol=sym,
        )
    if volume < spec.min_volume or volume > spec.max_volume:
        raise SpecViolationError(
            f"volume {volume} fuera de [{spec.min_volume}, {spec.max_volume}]",
            code="VOLUME_RANGE",
            symbol=sym,
        )
    if volume % spec.volume_step != 0:
        raise SpecViolationError(
            f"volume {volume} no es múltiplo de volume_step {spec.volume_step}",
            code="VOLUME_STEP",
            symbol=sym,
        )


__all__ = [
    "OPEN_SCAN_DAYS",
    "compute_market_status",
    "spec_asof",
    "validate_order",
]
