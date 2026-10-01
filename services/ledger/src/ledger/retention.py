"""retention — purga por TTL de claves de idempotencia y outbox (L §9, ADR-0011, BUILD-025).

BUILD-025 (F2.4): `RetentionSweep` replica el ciclo de vida de `OutboxRelay`
(task asyncio con `start`/`stop` y una pasada por intervalo) para eliminar solo
las filas de retención que L §9 permite purgar:

- `ledger_idempotency_keys`: TTL 7 días ya codificado en `expires_at` al
  escribir la clave (`store._run` usa `idempotency_ttl_seconds`); aquí solo se
  borra lo vencido, sin ventana redundante en los ajustes.
- `outbox_events`: 30 días tras `published_at` o `dead_lettered_at`
  (L §9 "TTL 30 días tras published"). Solo las filas finalizadas; las
  pendientes de publicar son backlog y no se tocan aunque tengan días.

Los asientos financieros (`ledger_entries`, `ledger_transactions`) son
permanentes (ADR-0011 §7, L §9 "Eliminación: Nunca DELETE"): este módulo no los
referencia y su trigger/red `models._forbid` los protege además.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from datetime import datetime, timedelta

from platform_kernel.clock import utcnow
from prometheus_client import Counter
from sqlalchemy import ColumnElement, Delete, delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ledger.config import LedgerSettings
from ledger.metrics import _shared_metric
from ledger.models import LedgerIdempotencyKey, OutboxEvent

logger = logging.getLogger("ledger.retention")

PURGED_COUNTER: Counter = _shared_metric(
    Counter,
    "platform_retention_purged_total",
    "Filas eliminadas por la purga de retención del ledger",
    ["service", "kind"],
)

KIND_IDEMPOTENCY_KEY = "idempotency_key"
KIND_OUTBOX_EVENT = "outbox_event"


def outbox_retention_cutoff(now: datetime, retention_days: int) -> datetime:
    """Corte del outbox: `retention_days` (30 en L §9) antes de `now`."""
    return now - timedelta(days=retention_days)


def outbox_retention_condition(cutoff: datetime) -> ColumnElement[bool]:
    """Filas finalizadas hace `cutoff` o más: publicadas o enviadas a la DLQ.

    Las filas sin `published_at` ni `dead_lettered_at` son backlog pendiente y
    nunca cumplen la condición, aunque su `created_at` tenga meses.
    """
    return (OutboxEvent.published_at.is_not(None) & (OutboxEvent.published_at <= cutoff)) | (
        OutboxEvent.dead_lettered_at.is_not(None) & (OutboxEvent.dead_lettered_at <= cutoff)
    )


async def _purge(session: AsyncSession, statement: Delete, batch_size: int) -> int:
    """Ejecuta `statement` en tandas de `batch_size` filas con commit por tanda.

    Cada DELETE acota su impacto con `IN (SELECT ... LIMIT n)` para no retener
    bloqueos largos sobre la tabla (L §9).
    """
    total = 0
    while True:
        result = await session.execute(statement)
        await session.commit()
        # `session.execute` tipa como `Result`; el `CursorResult` real expone rowcount
        rowcount: int | None = getattr(result, "rowcount", None)
        purged = max(int(rowcount or 0), 0)
        total += purged
        if purged < batch_size:
            return total


class RetentionSweep:
    """Purga por TTL de `ledger_idempotency_keys` y `outbox_events` (L §9, BUILD-025).

    Mismo ciclo de vida que `OutboxRelay`: `start` lanza la task
    `ledger-retention-sweep`, que ejecuta `sweep_once` al inicio y después cada
    `retention_sweep_interval_seconds`; `stop` la cancela.
    """

    def __init__(self, session_factory: async_sessionmaker[AsyncSession], settings: LedgerSettings) -> None:
        self._session_factory = session_factory
        self._settings = settings
        self._task: asyncio.Task[None] | None = None
        self._stopped = asyncio.Event()

    async def start(self) -> None:
        self._stopped.clear()
        self._task = asyncio.create_task(self._run(), name="ledger-retention-sweep")

    async def stop(self) -> None:
        self._stopped.set()
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def _run(self) -> None:
        interval_s = self._settings.retention_sweep_interval_seconds
        while not self._stopped.is_set():
            try:
                await self.sweep_once()
            except Exception:
                logger.exception("ciclo de retención del ledger falló")
            try:
                await asyncio.wait_for(self._stopped.wait(), timeout=interval_s)
            except TimeoutError:
                continue

    async def sweep_once(self) -> dict[str, int]:
        """Una pasada de purga; devuelve las filas eliminadas por tipo."""
        settings = self._settings
        batch_size = settings.retention_batch_size
        now = utcnow()
        cutoff = outbox_retention_cutoff(now, settings.outbox_retention_days)
        expired_keys = (
            select(LedgerIdempotencyKey.idempotency_key).where(LedgerIdempotencyKey.expires_at <= now).limit(batch_size)
        )
        finalized_events = select(OutboxEvent.id).where(outbox_retention_condition(cutoff)).limit(batch_size)

        async with self._session_factory() as session:
            counts = {
                "idempotency_keys": await _purge(
                    session,
                    delete(LedgerIdempotencyKey).where(LedgerIdempotencyKey.idempotency_key.in_(expired_keys)),
                    batch_size,
                ),
                "outbox_events": await _purge(
                    session,
                    delete(OutboxEvent).where(OutboxEvent.id.in_(finalized_events)),
                    batch_size,
                ),
            }

        logger.info(
            "retención del ledger ejecutada",
            extra={
                "extra_fields": {
                    "idempotency_keys": counts["idempotency_keys"],
                    "outbox_events": counts["outbox_events"],
                    "outbox_retention_days": settings.outbox_retention_days,
                }
            },
        )
        if counts["idempotency_keys"]:
            PURGED_COUNTER.labels(settings.service_name, KIND_IDEMPOTENCY_KEY).inc(counts["idempotency_keys"])
        if counts["outbox_events"]:
            PURGED_COUNTER.labels(settings.service_name, KIND_OUTBOX_EVENT).inc(counts["outbox_events"])
        return counts


__all__ = [
    "KIND_IDEMPOTENCY_KEY",
    "KIND_OUTBOX_EVENT",
    "PURGED_COUNTER",
    "RetentionSweep",
    "outbox_retention_condition",
    "outbox_retention_cutoff",
]
