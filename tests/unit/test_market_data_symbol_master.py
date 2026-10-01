"""Pruebas unitarias del symbol master (BUILD-028, REQ-025/REQ-099, K §2).

Ventanas de sesión (UTC, ISO weekday: lunes=0), prioridad
`suspensión > festivo > horario`, `spec_asof` versionado y `validate_order`
con los códigos golden: TICK_SIZE, VOLUME_RANGE, VOLUME_STEP, PRICE_POSITIVE,
MARKET_CLOSED y MARKET_HALTED.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal

import pytest
from market_data.domain.errors import MarketClosedError, MarketHaltedError, SpecViolationError
from market_data.domain.models import (
    CanonicalDataError,
    InstrumentSpec,
    MarketStatus,
    Suspension,
    SymbolMetadata,
    TradingSession,
)
from market_data.domain.symbol_master import compute_market_status, spec_asof, validate_order

FOREX = "EUR/USD"
CRYPTO = "BTC/USD"
#: 2026-09-29 es un martes; 2026-10-03 sábado y 2026-10-04 domingo.
TUE_NOON = datetime(2026, 9, 29, 12, 0, tzinfo=UTC)


def _forex_sessions() -> tuple[TradingSession, ...]:
    return tuple(
        TradingSession(
            symbol=FOREX,
            weekday=weekday,
            open_utc=time(22, 0),
            close_utc=time(21, 0),  # open > close ⇒ cruce de medianoche
            timezone="Etc/UTC",
            session_type="regular",
            holiday_calendar="FX_DEMO",
        )
        for weekday in (6, 0, 1, 2, 3)
    )


def _crypto_sessions() -> tuple[TradingSession, ...]:
    return tuple(
        TradingSession(
            symbol=CRYPTO,
            weekday=weekday,
            open_utc=time(0, 0),
            close_utc=time(0, 0),  # open == close ⇒ 24 h
            timezone="Etc/UTC",
            session_type="regular",
            holiday_calendar=None,
        )
        for weekday in range(7)
    )


def _spec(
    symbol: str = FOREX,
    *,
    version: int = 1,
    valid_from: datetime = datetime(2026, 1, 1, tzinfo=UTC),
    valid_to: datetime | None = None,
    tick: str = "0.00001",
    min_volume: str = "0.01",
    max_volume: str = "10000000",
    step: str = "0.01",
) -> InstrumentSpec:
    return InstrumentSpec(
        symbol=symbol,
        version=version,
        valid_from=valid_from,
        valid_to=valid_to,
        tick_size=Decimal(tick),
        pip_size=Decimal("0.0001"),
        contract_size=Decimal("100000"),
        min_volume=Decimal(min_volume),
        max_volume=Decimal(max_volume),
        volume_step=Decimal(step),
    )


def _status(status: str, reason: str = "session") -> MarketStatus:
    return MarketStatus(
        symbol=FOREX,
        status=status,  # type: ignore[arg-type]  # estados válidos por construcción
        reason=reason,
        as_of=TUE_NOON,
        source="MOCK",
        simulated=True,
    )


def _market(
    *,
    sessions: tuple[TradingSession, ...],
    now: datetime,
    suspension: Suspension | None = None,
    holidays: dict[date, str] | None = None,
    symbol: str = FOREX,
) -> MarketStatus:
    return compute_market_status(
        symbol=symbol,
        sessions=sessions,
        suspension=suspension,
        holidays=holidays or {},
        source="MOCK",
        simulated=True,
        now=now,
    )


def test_crypto_24_7_abierto_cualquier_hora() -> None:
    status = _market(sessions=_crypto_sessions(), now=datetime(2026, 9, 29, 3, 14, tzinfo=UTC), symbol=CRYPTO)
    assert status.status == "open"
    assert status.reason == "session"
    assert status.next_close == datetime(2026, 9, 30, 0, 0, tzinfo=UTC)
    assert status.next_open is None


def test_forex_abierto_el_martes_al_mediodia() -> None:
    status = _market(sessions=_forex_sessions(), now=TUE_NOON)
    assert status.status == "open"
    # Ventana lunes 22:00 → martes 21:00 (cruce de medianoche).
    assert status.next_close == datetime(2026, 9, 29, 21, 0, tzinfo=UTC)


def test_forex_break_diario_closed_out_of_hours() -> None:
    status = _market(sessions=_forex_sessions(), now=datetime(2026, 9, 29, 21, 30, tzinfo=UTC))
    assert status.status == "closed"
    assert status.reason == "out_of_hours"
    assert status.next_open == datetime(2026, 9, 29, 22, 0, tzinfo=UTC)


def test_forex_fin_de_semana_closed_con_next_open_domingo() -> None:
    status = _market(sessions=_forex_sessions(), now=datetime(2026, 10, 3, 12, 0, tzinfo=UTC))
    assert status.status == "closed"
    assert status.next_open == datetime(2026, 10, 4, 22, 0, tzinfo=UTC)


def test_forex_domingo_por_la_noche_abierto() -> None:
    status = _market(sessions=_forex_sessions(), now=datetime(2026, 10, 4, 23, 0, tzinfo=UTC))
    assert status.status == "open"
    assert status.next_close == datetime(2026, 10, 5, 21, 0, tzinfo=UTC)


def test_suspension_vigente_halted_con_motivo() -> None:
    suspension = Suspension(
        symbol=FOREX,
        code="manual",
        reason="mantenimiento programado",
        starts_at=TUE_NOON - timedelta(hours=1),
    )
    status = _market(sessions=_forex_sessions(), now=TUE_NOON, suspension=suspension)
    assert status.status == "halted"
    assert status.reason == "suspended:manual"
    assert status.next_close is None
    assert status.next_open is not None


def test_suspension_expirada_se_ignora() -> None:
    suspension = Suspension(
        symbol=FOREX,
        code="news",
        reason="comunicado",
        starts_at=TUE_NOON - timedelta(hours=3),
        ends_at=TUE_NOON - timedelta(hours=1),
    )
    status = _market(sessions=_forex_sessions(), now=TUE_NOON, suspension=suspension)
    assert status.status == "open"


def test_festivo_del_dia_cierra_con_motivo() -> None:
    status = _market(
        sessions=_forex_sessions(),
        now=TUE_NOON,
        holidays={date(2026, 9, 29): "Festivo Demo"},
    )
    assert status.status == "closed"
    assert status.reason == "holiday:Festivo Demo"


def test_next_open_salta_el_festivo() -> None:
    status = _market(
        sessions=_forex_sessions(),
        now=datetime(2026, 10, 3, 12, 0, tzinfo=UTC),  # sábado
        holidays={date(2026, 10, 4): "Festivo"},  # domingo festivo
    )
    assert status.status == "closed"
    assert status.next_open == datetime(2026, 10, 5, 22, 0, tzinfo=UTC)


def test_prioridad_suspension_sobre_festivo() -> None:
    suspension = Suspension(
        symbol=FOREX,
        code="news",
        reason="comunicado",
        starts_at=TUE_NOON - timedelta(hours=1),
    )
    status = _market(
        sessions=_forex_sessions(),
        now=TUE_NOON,
        suspension=suspension,
        holidays={date(2026, 9, 29): "Festivo Demo"},
    )
    assert status.status == "halted"
    assert status.reason == "suspended:news"


def test_compute_market_status_rechaza_now_naive() -> None:
    with pytest.raises(CanonicalDataError, match="zona horaria"):
        _market(sessions=_forex_sessions(), now=datetime(2026, 9, 29, 12, 0))


def test_spec_asof_elige_la_version_vigente() -> None:
    v1 = _spec(version=1, valid_from=datetime(2026, 1, 1, tzinfo=UTC), valid_to=datetime(2026, 7, 1, tzinfo=UTC))
    v2 = _spec(version=2, valid_from=datetime(2026, 7, 1, tzinfo=UTC), valid_to=None)
    assert spec_asof([v1, v2], datetime(2026, 3, 1, tzinfo=UTC)).version == 1
    assert spec_asof([v1, v2], datetime(2026, 8, 1, tzinfo=UTC)).version == 2
    assert spec_asof([v1, v2], datetime(2026, 7, 1, tzinfo=UTC)).version == 2  # borde: valid_to excluyente
    assert spec_asof([v1, v2], datetime(2025, 12, 31, tzinfo=UTC)) is None  # antes de valid_from


def test_spec_asof_rechaza_now_naive() -> None:
    with pytest.raises(CanonicalDataError, match="zona horaria"):
        spec_asof([_spec()], datetime(2026, 3, 1))


def test_validate_order_orden_valida_no_lanza() -> None:
    validate_order(spec=_spec(), status=_status("open"), price=Decimal("1.10000"), volume=Decimal("1"))


def test_validate_order_tick_size() -> None:
    with pytest.raises(SpecViolationError) as exc:
        validate_order(
            spec=_spec(CRYPTO, tick="0.01", min_volume="0.0001", max_volume="100", step="0.0001"),
            status=_status("open"),
            price=Decimal("1.105"),
            volume=Decimal("1"),
        )
    assert exc.value.code == "TICK_SIZE"
    assert exc.value.status_code == 422
    assert exc.value.type_uri == "urn:platform:error:spec-violation"
    assert exc.value.extra["symbol"] == CRYPTO


def test_validate_order_volumen_fuera_de_rango() -> None:
    spec = _spec(CRYPTO, tick="0.01", min_volume="0.0001", max_volume="100", step="0.0001")
    with pytest.raises(SpecViolationError) as bajo:
        validate_order(spec=spec, status=_status("open"), price=Decimal("1.10"), volume=Decimal("0.00005"))
    assert bajo.value.code == "VOLUME_RANGE"
    with pytest.raises(SpecViolationError) as alto:
        validate_order(spec=spec, status=_status("open"), price=Decimal("1.10"), volume=Decimal("1000"))
    assert alto.value.code == "VOLUME_RANGE"


def test_validate_order_volumen_fuera_del_step() -> None:
    spec = _spec(CRYPTO, tick="0.01", min_volume="0.0001", max_volume="100", step="0.0001")
    with pytest.raises(SpecViolationError) as exc:
        validate_order(spec=spec, status=_status("open"), price=Decimal("1.10"), volume=Decimal("0.00015"))
    assert exc.value.code == "VOLUME_STEP"


def test_validate_order_precio_no_positivo() -> None:
    with pytest.raises(SpecViolationError) as exc:
        validate_order(spec=_spec(), status=_status("open"), price=Decimal("0"), volume=Decimal("1"))
    assert exc.value.code == "PRICE_POSITIVE"


def test_validate_order_mercado_cerrado_golden() -> None:
    with pytest.raises(MarketClosedError) as exc:
        validate_order(
            spec=_spec(),
            status=_status("closed", reason="out_of_hours"),
            price=Decimal("1.10000"),
            volume=Decimal("1"),
        )
    assert exc.value.code == "MARKET_CLOSED"
    assert exc.value.status_code == 409
    assert exc.value.type_uri == "urn:platform:error:market-closed"


def test_validate_order_mercado_suspendido_golden() -> None:
    with pytest.raises(MarketHaltedError) as exc:
        validate_order(
            spec=_spec(),
            status=_status("halted", reason="suspended:news"),
            price=Decimal("1.10000"),
            volume=Decimal("1"),
        )
    assert exc.value.code == "MARKET_HALTED"
    assert exc.value.status_code == 409
    assert exc.value.type_uri == "urn:platform:error:market-halted"


def test_validate_order_estado_se_anteune_a_la_spec() -> None:
    with pytest.raises(MarketClosedError):
        validate_order(spec=_spec(), status=_status("closed"), price=Decimal("1.10003"), volume=Decimal("0"))


def test_validate_order_rechaza_float() -> None:
    with pytest.raises(CanonicalDataError, match="Decimal"):
        validate_order(spec=_spec(), status=_status("open"), price=1.1, volume=Decimal("1"))  # type: ignore[arg-type]
    with pytest.raises(CanonicalDataError, match="Decimal"):
        validate_order(spec=_spec(), status=_status("open"), price=Decimal("1.10000"), volume=1.0)  # type: ignore[arg-type]


def test_symbol_metadata_rechaza_estado_desconocido() -> None:
    with pytest.raises(CanonicalDataError, match="status"):
        SymbolMetadata(
            symbol="XAU/USD",
            display_name="Oro",
            asset_class="forex",
            base_currency="XAU",
            quote_currency="USD",
            status="activo",  # type: ignore[arg-type]
            source="MOCK",
        )


def test_trading_session_valida_weekday_y_horas() -> None:
    with pytest.raises(CanonicalDataError, match="weekday"):
        TradingSession(
            symbol=FOREX,
            weekday=7,
            open_utc=time(22, 0),
            close_utc=time(21, 0),
            timezone="Etc/UTC",
            session_type="regular",
        )
    with pytest.raises(CanonicalDataError, match="zona"):
        TradingSession(
            symbol=FOREX,
            weekday=0,
            open_utc=time(22, 0, tzinfo=UTC),  # type: ignore[arg-type]
            close_utc=time(21, 0),
            timezone="Etc/UTC",
            session_type="regular",
        )


def test_instrument_spec_valida_rangos_y_version() -> None:
    with pytest.raises(CanonicalDataError, match="version"):
        _spec(version=0)
    with pytest.raises(CanonicalDataError, match="max_volume"):
        _spec(min_volume="10", max_volume="1")
    with pytest.raises(CanonicalDataError, match="valid_to"):
        _spec(valid_from=datetime(2026, 7, 1, tzinfo=UTC), valid_to=datetime(2026, 1, 1, tzinfo=UTC))


def test_price_precision_se_deriva_del_tick() -> None:
    assert _spec(tick="0.00001").price_precision == 5
    assert _spec(tick="0.01").price_precision == 2
    assert _spec(tick="1").price_precision == 0
    assert _spec().is_current is True
    assert _spec(valid_to=datetime(2026, 7, 1, tzinfo=UTC)).is_current is False
