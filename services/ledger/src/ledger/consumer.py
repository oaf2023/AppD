"""consumer - fondeo y recarga de la cuenta demo desde eventos de `accounts` (F2.3).

`DemoAccountCreated` (#16) fondea la demo con el saldo inicial y
`DemoBalanceReset` (#17) ajusta el balance al nuevo valor, ambos mediante la
misma primitiva idempotente de postings (`post_transaction`, ADR-0010/ADR-0011).
La clave de idempotencia deriva del `event_id`: una reentrega del mismo evento
produce un solo asiento (at-least-once + deduplicación, P-event-catalog §3.3).

Mapeo de asientos (L §7.2 y §7.1):
- depósito (delta > 0): `DEBIT 1200.RECEIVABLE.PSP.<moneda>` / `CREDIT 2000.PAYABLE.CLIENT.<moneda>.u_<hex>`;
- ajuste a la baja (delta < 0): inverso del depósito (`DEBIT cliente` / `CREDIT 1200`).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import uuid
from decimal import Decimal

from aiokafka import AIOKafkaConsumer
from aiokafka.structs import ConsumerRecord, TopicPartition
from platform_contracts.events import DEMO_ACCOUNT_CREATED, DEMO_BALANCE_RESET, topic_for_event
from platform_kernel.errors import ValidationError
from platform_kernel.events import EventEnvelope
from platform_kernel.money import to_decimal
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ledger.config import LedgerSettings
from ledger.postings import canonical_amount
from ledger.schemas import EntryIn, PostingsIn
from ledger.store import compute_owner_balances, post_transaction

logger = logging.getLogger("ledger.consumer")

GROUP_ID = "ledger-service"
REQUEST_TIMEOUT_MS = 5000
RETRY_DELAY_SECONDS = 5.0
MAX_ERROR_LENGTH = 2000

DEMO_ACCOUNT_CREATED_TOPIC = topic_for_event("accounts", "TradingAccount", DEMO_ACCOUNT_CREATED)
DEMO_BALANCE_RESET_TOPIC = topic_for_event("accounts", "TradingAccount", DEMO_BALANCE_RESET)

SUBJECT = "ledger.consumer"


def client_account_code(currency: str, owner_id: uuid.UUID) -> str:
    """Código de la cuenta de crédito por usuario+moneda (L §7.1: `2000.PAYABLE.CLIENT`).

    El sufijo `u_<hex>` evita los guiones del UUID (patrón de código, ADR-0011 §1).
    """
    return f"2000.PAYABLE.CLIENT.{currency}.u_{owner_id.hex}"


def control_account_code(currency: str) -> str:
    """Cuenta de control de depósitos en tránsito (L §7.1: `1200.RECEIVABLE.PSP`)."""
    return f"1200.RECEIVABLE.PSP.{currency}"


async def _owner_balance(session: AsyncSession, owner_id: uuid.UUID, currency: str) -> Decimal:
    for owner, code, balance in await compute_owner_balances(session, owner_id):
        if owner == owner_id and code == currency:
            return balance
    return Decimal(0)


async def _post(
    session: AsyncSession,
    *,
    tx_type: str,
    envelope: EventEnvelope,
    entries: list[EntryIn],
    idempotency_suffix: str,
) -> bool:
    cmd = PostingsIn(
        type=tx_type,  # type: ignore[arg-type]
        correlation_id=uuid.UUID(envelope.event_id),
        causation_id=uuid.UUID(envelope.event_id),
        occurred_at=envelope.timestamp,
        metadata={"event_id": envelope.event_id, "event_type": envelope.event_type},
        entries=entries,
    )
    _posting, replayed = await post_transaction(
        session,
        cmd,
        idempotency_key=f"{idempotency_suffix}:{envelope.event_id}",
        subject=SUBJECT,
    )
    return not replayed


async def fund_demo_from_event(session: AsyncSession, settings: LedgerSettings, envelope: EventEnvelope) -> bool:
    """Fondea la cuenta demo con `initial_balance` (#16). Devuelve False si se omitió."""
    try:
        user_id = uuid.UUID(str(envelope.payload["user_id"]))
        currency = str(envelope.payload["currency"])
        initial_balance = to_decimal(str(envelope.payload["initial_balance"]))
    except (KeyError, TypeError, ValueError) as exc:
        logger.error(
            "payload DemoAccountCreated inválido; se omite el fondeo",
            extra={"extra_fields": {"event_id": envelope.event_id, "error": str(exc)[:MAX_ERROR_LENGTH]}},
        )
        await session.rollback()
        return False
    if initial_balance <= 0:
        logger.info(
            "initial_balance no positivo; se omite el fondeo",
            extra={"extra_fields": {"event_id": envelope.event_id}},
        )
        await session.rollback()
        return False
    try:
        return await _post(
            session,
            tx_type="deposit",
            envelope=envelope,
            entries=[
                EntryIn(
                    account_code=control_account_code(currency),
                    direction="D",
                    amount=canonical_amount(initial_balance),
                    currency=currency,
                ),
                EntryIn(
                    account_code=client_account_code(currency, user_id),
                    direction="C",
                    amount=canonical_amount(initial_balance),
                    currency=currency,
                    owner_id=user_id,
                    owner_type="user",
                ),
            ],
            idempotency_suffix="demo-funding",
        )
    except ValidationError:
        logger.error(
            "fondeo de demo rechazado por reglas de posting; se omite",
            extra={"extra_fields": {"event_id": envelope.event_id}},
        )
        await session.rollback()
        return False


async def reset_demo_balance_from_event(
    session: AsyncSession, settings: LedgerSettings, envelope: EventEnvelope
) -> bool:
    """Ajusta el balance de la demo a `new_balance` (#17). Devuelve False si no hay delta."""
    try:
        user_id = uuid.UUID(str(envelope.payload["user_id"]))
        currency = str(envelope.payload["currency"])
        new_balance = to_decimal(str(envelope.payload["new_balance"]))
    except (KeyError, TypeError, ValueError) as exc:
        logger.error(
            "payload DemoBalanceReset inválido; se omite el reinicio",
            extra={"extra_fields": {"event_id": envelope.event_id, "error": str(exc)[:MAX_ERROR_LENGTH]}},
        )
        await session.rollback()
        return False
    if new_balance < 0:
        logger.error(
            "new_balance negativo; se omite el reinicio",
            extra={"extra_fields": {"event_id": envelope.event_id}},
        )
        await session.rollback()
        return False
    current = await _owner_balance(session, user_id, currency)
    delta = new_balance - current
    if delta == 0:
        logger.info(
            "sin delta en el reinicio de demo; se omite el posting",
            extra={"extra_fields": {"event_id": envelope.event_id}},
        )
        await session.rollback()
        return False
    entries = [
        EntryIn(
            account_code=control_account_code(currency),
            direction="C" if delta < 0 else "D",
            amount=canonical_amount(abs(delta)),
            currency=currency,
        ),
        EntryIn(
            account_code=client_account_code(currency, user_id),
            direction="D" if delta < 0 else "C",
            amount=canonical_amount(abs(delta)),
            currency=currency,
            owner_id=user_id,
            owner_type="user",
        ),
    ]
    try:
        return await _post(
            session,
            tx_type="deposit" if delta > 0 else "adjustment",
            envelope=envelope,
            entries=entries,
            idempotency_suffix="demo-reset",
        )
    except ValidationError:
        logger.error(
            "reinicio de demo rechazado por reglas de posting; se omite",
            extra={"extra_fields": {"event_id": envelope.event_id}},
        )
        await session.rollback()
        return False


class LedgerEventConsumer:
    """Consume `accounts.trading_account.demo_account_created` y `...demo_balance_reset`."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession], settings: LedgerSettings) -> None:
        self._session_factory = session_factory
        self._settings = settings
        self._consumer: AIOKafkaConsumer | None = None
        self._task: asyncio.Task[None] | None = None
        self._stopped = asyncio.Event()

    async def start(self) -> None:
        self._stopped.clear()
        self._task = asyncio.create_task(self._run(), name="ledger-event-consumer")

    async def stop(self) -> None:
        self._stopped.set()
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        await self._close_consumer()

    async def _run(self) -> None:
        while not self._stopped.is_set():
            try:
                await self._consume()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning(
                    "consumidor de eventos interrumpido; se reintentará",
                    extra={"extra_fields": {"service": "ledger"}},
                )
                await self._close_consumer()
            try:
                await asyncio.wait_for(self._stopped.wait(), timeout=RETRY_DELAY_SECONDS)
            except TimeoutError:
                continue

    async def _consume(self) -> None:
        consumer = AIOKafkaConsumer(
            DEMO_ACCOUNT_CREATED_TOPIC,
            DEMO_BALANCE_RESET_TOPIC,
            bootstrap_servers=self._settings.redpanda_bootstrap_servers,
            group_id=GROUP_ID,
            auto_offset_reset="earliest",
            enable_auto_commit=False,
            request_timeout_ms=REQUEST_TIMEOUT_MS,
            client_id=f"{self._settings.service_name}-event-consumer",
        )
        self._consumer = consumer
        try:
            await consumer.start()
            while not self._stopped.is_set():
                message = await consumer.getone()
                await self._handle(consumer, message)
        finally:
            await self._close_consumer()

    async def _handle(self, consumer: AIOKafkaConsumer, message: ConsumerRecord) -> None:
        offset = TopicPartition(message.topic, message.partition)
        try:
            envelope = EventEnvelope.model_validate(json.loads(message.value))
        except Exception:
            # sin payload en el log: puede contener datos sensibles
            logger.error(
                "mensaje de evento inválido; se omite",
                extra={
                    "extra_fields": {"topic": message.topic, "partition": message.partition, "offset": message.offset}
                },
            )
            await consumer.commit({offset: message.offset + 1})
            return
        if envelope.event_type == DEMO_ACCOUNT_CREATED:
            async with self._session_factory() as session:
                created = await fund_demo_from_event(session, self._settings, envelope)
            if created:
                logger.info(
                    "cuenta demo fondeada",
                    extra={"extra_fields": {"event_id": envelope.event_id}},
                )
        elif envelope.event_type == DEMO_BALANCE_RESET:
            async with self._session_factory() as session:
                reset = await reset_demo_balance_from_event(session, self._settings, envelope)
            if reset:
                logger.info(
                    "balance de demo reiniciado",
                    extra={"extra_fields": {"event_id": envelope.event_id}},
                )
        await consumer.commit({offset: message.offset + 1})

    async def _close_consumer(self) -> None:
        consumer, self._consumer = self._consumer, None
        if consumer is not None:
            with contextlib.suppress(Exception):
                await consumer.stop()


__all__ = [
    "DEMO_ACCOUNT_CREATED_TOPIC",
    "DEMO_BALANCE_RESET_TOPIC",
    "GROUP_ID",
    "LedgerEventConsumer",
    "client_account_code",
    "control_account_code",
    "fund_demo_from_event",
    "reset_demo_balance_from_event",
]
