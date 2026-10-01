"""seed — catálogo demo del symbol master (BUILD-028, REQ-025/REQ-099).

Datos **simulados** etiquetados `source=MOCK`/`mode: demo` (X-07): specs y
horarios declarativos para el universo provisional del
`MockMarketDataProvider`, sin afirmar especificaciones de mercados reales.

- Festivos: calendario `FX_DEMO` **sin filas** — los cierres del forex se
  modelan con las sesiones (24/5: apertura domingo 22:00 UTC, cierre diario
  21:00 UTC, fin de semana cerrado; K §2). No se inventan feriados reales.
- Sesiones crypto: 24/7 (una fila por día con `open == close` ⇒ 24 h, ver
  semántica en `domain.models.TradingSession`).
- Un único origen de verdad: la migración `0002_symbol_master` y los tests
  importan estas mismas constantes.

Uso: `seed_statements()` devuelve los `INSERT ... ON CONFLICT DO NOTHING`
idempotentes; la migración los corre en sync y los tests en async.
"""

from __future__ import annotations

from datetime import UTC, datetime, time
from decimal import Decimal
from typing import Any

from sqlalchemy.dialects.postgresql import Insert
from sqlalchemy.dialects.postgresql import insert as pg_insert

from market_data.tables import InstrumentSpecRow, SymbolRow, TradingSessionRow

#: Inicio de la versión 1 del catálogo (fijo ⇒ determinista entre entornos).
SPEC_VALID_FROM = datetime(2026, 10, 1, tzinfo=UTC)

_FOREX_SESSIONS = tuple(
    {
        "weekday": weekday,
        "open_utc": time(22, 0),
        "close_utc": time(21, 0),  # open > close ⇒ ventana que cruza medianoche
        "timezone": "Etc/UTC",
        "session_type": "regular",
        "holiday_calendar": "FX_DEMO",
    }
    # ISO weekday: lunes=0 … domingo=6 → Sun(6)…Thu(3) ⇒ Sun 22:00 → Fri 21:00.
    for weekday in (6, 0, 1, 2, 3)
)

_CRYPTO_SESSIONS = tuple(
    {
        "weekday": weekday,
        "open_utc": time(0, 0),
        "close_utc": time(0, 0),  # open == close ⇒ ventana de 24 h
        "timezone": "Etc/UTC",
        "session_type": "regular",
        "holiday_calendar": None,
    }
    for weekday in range(7)
)


def _forex_spec(*, tick: str, min_volume: str, max_volume: str, step: str) -> dict[str, Any]:
    return {
        "version": 1,
        "valid_from": SPEC_VALID_FROM,
        "tick_size": Decimal(tick),
        "pip_size": Decimal(tick),
        "contract_size": Decimal("1"),
        "min_volume": Decimal(min_volume),
        "max_volume": Decimal(max_volume),
        "volume_step": Decimal(step),
        "margin_requirements": {"mode": "demo", "initial_rate": "0.01", "maintenance_rate": "0.005"},
        "fee_schedule": {"mode": "demo", "commission_rate": "0", "currency": "USD"},
        "swap_configuration": {"mode": "demo", "enabled": False},
        "jurisdiction_restrictions": [],
    }


CATALOG_SEED: tuple[dict[str, Any], ...] = (
    {
        "symbol": "EUR/USD",
        "display_name": "Euro / US Dollar",
        "asset_class": "forex",
        "base_currency": "EUR",
        "quote_currency": "USD",
        "status": "active",
        "source": "MOCK",
        "spec": _forex_spec(tick="0.00001", min_volume="0.01", max_volume="10000000", step="0.01"),
        "sessions": _FOREX_SESSIONS,
    },
    {
        "symbol": "GBP/USD",
        "display_name": "British Pound / US Dollar",
        "asset_class": "forex",
        "base_currency": "GBP",
        "quote_currency": "USD",
        "status": "active",
        "source": "MOCK",
        "spec": _forex_spec(tick="0.00001", min_volume="0.01", max_volume="10000000", step="0.01"),
        "sessions": _FOREX_SESSIONS,
    },
    {
        "symbol": "BTC/USD",
        "display_name": "Bitcoin / US Dollar",
        "asset_class": "crypto",
        "base_currency": "BTC",
        "quote_currency": "USD",
        "status": "active",
        "source": "MOCK",
        "spec": _forex_spec(tick="0.01", min_volume="0.0001", max_volume="100", step="0.0001"),
        "sessions": _CRYPTO_SESSIONS,
    },
    {
        "symbol": "ETH/USD",
        "display_name": "Ethereum / US Dollar",
        "asset_class": "crypto",
        "base_currency": "ETH",
        "quote_currency": "USD",
        "status": "active",
        "source": "MOCK",
        "spec": _forex_spec(tick="0.01", min_volume="0.001", max_volume="1000", step="0.001"),
        "sessions": _CRYPTO_SESSIONS,
    },
)


def seed_statements() -> list[Insert]:
    """`INSERT ... ON CONFLICT DO NOTHING` idempotentes del catálogo demo."""
    statements: list[Insert] = []
    for entry in CATALOG_SEED:
        statements.append(
            pg_insert(SymbolRow)
            .values(
                symbol=entry["symbol"],
                display_name=entry["display_name"],
                asset_class=entry["asset_class"],
                base_currency=entry["base_currency"],
                quote_currency=entry["quote_currency"],
                status=entry["status"],
                source=entry["source"],
            )
            .on_conflict_do_nothing()
        )
        spec = dict(entry["spec"])
        statements.append(pg_insert(InstrumentSpecRow).values(symbol=entry["symbol"], **spec).on_conflict_do_nothing())
        for session in entry["sessions"]:
            statements.append(
                pg_insert(TradingSessionRow).values(symbol=entry["symbol"], **session).on_conflict_do_nothing()
            )
    return statements


async def seed_catalog(session) -> None:  # type: ignore[no-untyped-def]
    """Aplica el seed en una sesión asíncrona (tests; `AsyncSession`)."""
    for statement in seed_statements():
        await session.execute(statement)


__all__ = ["CATALOG_SEED", "SPEC_VALID_FROM", "seed_catalog", "seed_statements"]
