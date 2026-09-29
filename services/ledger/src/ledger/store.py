"""store — escritura ACID de postings: cuentas, asientos, outbox e idempotencia.

Una sola transacción cubre: cuentas auto-creadas, `ledger_transactions`,
`ledger_entries`, la fila `outbox_events` con `LedgerPosted` y la clave de
idempotencia (ADR-0011 §5, L §5/§6). Si algo falla, no se escribe nada.

Sin importar cantidades ni códigos de cuenta en logs: `LedgerPosted` es
`CONFIDENTIAL` (P-event-catalog §4).
"""

from __future__ import annotations

import logging
import uuid
from collections.abc import Sequence
from datetime import timedelta
from typing import Literal, cast

from platform_kernel.clock import utcnow
from platform_kernel.errors import AppError, ConflictError, NotFoundError, ValidationError
from platform_kernel.events import build_event
from platform_kernel.ids import new_uuid7
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from ledger.config import get_ledger_settings
from ledger.metrics import POSTINGS_TOTAL
from ledger.models import LedgerAccount, LedgerEntry, LedgerIdempotencyKey, LedgerTransaction, OutboxEvent
from ledger.postings import (
    SYSTEM_OWNER_ID,
    EntryFact,
    PlanAccount,
    PostingRuleError,
    ResolvedEntry,
    advisory_lock_key,
    build_ledger_posted_payload,
    canonical_amount,
    plan_for_code,
    posting_request_hash,
    validate_posting_rules,
)
from ledger.schemas import EntryOut, PostingOut, PostingsIn, TxType

logger = logging.getLogger("ledger.store")

POSTING_ROUTE = "POST /internal/v1/postings"
AGGREGATE_TYPE = "LedgerTransaction"
EVENT_TYPE = "LedgerPosted"
EVENT_SCHEMA_VERSION = 1
CREATED_STATUS_CODE = 201

TYPE_IDEMPOTENCY_KEY_REUSE = "urn:platform:error:idempotency-key-reuse"
TYPE_IDEMPOTENCY_IN_PROGRESS = "urn:platform:error:idempotency-in-progress"


class _Replay(Exception):
    """Señal interna: la clave ya tiene una respuesta almacenada (rollback + replay)."""

    def __init__(self, posting: PostingOut) -> None:
        super().__init__("replay idempotente")
        self.posting = posting


def request_hash_for(cmd: PostingsIn, subject: str) -> str:
    """SHA-256 canónico del comando + sujeto autenticado (ADR-0010 §1)."""
    return posting_request_hash(
        tx_type=cmd.type,
        correlation_id=cmd.correlation_id,
        causation_id=cmd.causation_id,
        occurred_at=cmd.occurred_at,
        metadata=cmd.metadata,
        reverses_tx_id=cmd.reverses_tx_id,
        entries=[entry.model_dump(mode="python") for entry in cmd.entries],
        subject=subject,
    )


async def post_transaction(
    session: AsyncSession,
    cmd: PostingsIn,
    *,
    idempotency_key: str,
    subject: str,
) -> tuple[PostingOut, bool]:
    """Escribe un posting de forma idempotente. Devuelve `(posting, reemitido)`."""
    request_hash = request_hash_for(cmd, subject)
    try:
        posting = await _run(session, cmd, idempotency_key=idempotency_key, subject=subject, request_hash=request_hash)
    except _Replay as replay:
        await session.rollback()
        logger.info(
            "posting reemitido por idempotencia",
            extra={
                "extra_fields": {
                    "transaction_id": str(replay.posting.transaction_id),
                    "type": replay.posting.type,
                    "subject": subject,
                }
            },
        )
        return replay.posting, True
    except BaseException:
        await session.rollback()
        raise
    await session.commit()
    POSTINGS_TOTAL.labels(posting.type).inc()
    logger.info(
        "posting registrado",
        extra={
            "extra_fields": {
                "transaction_id": str(posting.transaction_id),
                "type": posting.type,
                "correlation_id": str(posting.correlation_id),
                "entries": len(posting.entries),
                "subject": subject,
            }
        },
    )
    return posting, False


async def _run(
    session: AsyncSession,
    cmd: PostingsIn,
    *,
    idempotency_key: str,
    subject: str,
    request_hash: str,
) -> PostingOut:
    await _acquire_key_lock(session, idempotency_key)

    try:
        facts = validate_posting_rules(
            tx_type=cmd.type,
            entries=[entry.model_dump(mode="python") for entry in cmd.entries],
            reverses_tx_id=cmd.reverses_tx_id,
        )
    except PostingRuleError as exc:
        raise ValidationError(str(exc)) from exc

    accounts = await _resolve_accounts(session, facts)
    if cmd.reverses_tx_id is not None:
        await _assert_reversal(session, cmd.reverses_tx_id, [f.reverses_entry_id for f in facts])

    transaction = LedgerTransaction(
        id=new_uuid7(),
        type=cmd.type,
        correlation_id=cmd.correlation_id,
        causation_id=cmd.causation_id,
        occurred_at=cmd.occurred_at,
        tx_metadata=dict(cmd.metadata),
        reverses_tx_id=cmd.reverses_tx_id,
        created_at=utcnow(),
    )
    session.add(transaction)

    resolved: list[ResolvedEntry] = []
    for fact, account in zip(facts, accounts, strict=True):
        entry_id = new_uuid7()
        session.add(
            LedgerEntry(
                id=entry_id,
                transaction_id=transaction.id,
                account_id=account.id,
                direction=fact.direction,
                amount=fact.amount,
                currency=fact.currency,
                reverses_entry_id=fact.reverses_entry_id,
                position=fact.position,
                created_at=utcnow(),
            )
        )
        resolved.append(
            ResolvedEntry(
                entry_id=entry_id,
                position=fact.position,
                account_id=account.id,
                account_code=fact.account_code,
                direction=fact.direction,
                amount=fact.amount,
                currency=fact.currency,
                reverses_entry_id=fact.reverses_entry_id,
            )
        )

    await session.flush()
    await _assert_balanced_in_db(session, transaction.id)

    posting = _build_posting(transaction, resolved, cmd.type)
    await _store_outbox_event(session, transaction=transaction, cmd=cmd, entries=resolved)

    settings = get_ledger_settings()
    claim = await session.execute(
        pg_insert(LedgerIdempotencyKey)
        .values(
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            subject=subject,
            transaction_id=transaction.id,
            status_code=CREATED_STATUS_CODE,
            response=posting.model_dump(mode="json"),
            expires_at=utcnow() + timedelta(seconds=settings.idempotency_ttl_seconds),
            created_at=utcnow(),
        )
        .on_conflict_do_nothing(index_elements=["idempotency_key"])
        .returning(LedgerIdempotencyKey.idempotency_key)
    )
    # psycopg3 expone rowcount -1 en INSERT ... ON CONFLICT sin RETURNING
    # (SQLAlchemy Core); la fila devuelta es la única señal fiable.
    if claim.scalar_one_or_none() is None:
        raise _Replay(await _load_stored_posting(session, idempotency_key=idempotency_key, request_hash=request_hash))
    return posting


# --------------------------------------------------------------------------- idempotencia


async def _acquire_key_lock(session: AsyncSession, idempotency_key: str) -> None:
    """Lock de entrada para la clave: los concurrentes reciben 409 (ADR-0010 §2)."""
    result = await session.execute(
        text("SELECT pg_try_advisory_xact_lock(CAST(:key AS bigint)) AS locked"),
        {"key": advisory_lock_key(idempotency_key)},
    )
    if not result.scalar():
        raise AppError(
            409,
            TYPE_IDEMPOTENCY_IN_PROGRESS,
            "Idempotencia en curso",
            "Otra ejecución con la misma Idempotency-Key está en curso; reintenta en 1 s (ADR-0010)",
            extra={"retry_after": 1},
        )


async def _load_stored_posting(session: AsyncSession, *, idempotency_key: str, request_hash: str) -> PostingOut:
    row = (
        await session.execute(
            select(LedgerIdempotencyKey).where(LedgerIdempotencyKey.idempotency_key == idempotency_key)
        )
    ).scalar_one_or_none()
    if row is None:
        raise AppError(
            409,
            TYPE_IDEMPOTENCY_IN_PROGRESS,
            "Idempotencia en curso",
            "La clave se reclamó y aún no tiene respuesta; reintenta en 1 s (ADR-0010)",
            extra={"retry_after": 1},
        )
    if row.request_hash != request_hash:
        raise AppError(
            409,
            TYPE_IDEMPOTENCY_KEY_REUSE,
            "Idempotency-Key reutilizada",
            "La misma Idempotency-Key ya se usó con un cuerpo distinto (ADR-0010)",
            extra={"original_created_at": row.created_at.isoformat() if row.created_at else None},
        )
    if row.response is None:
        raise AppError(
            409,
            TYPE_IDEMPOTENCY_IN_PROGRESS,
            "Idempotencia en curso",
            "La clave se reclamó y aún no tiene respuesta; reintenta en 1 s (ADR-0010)",
            extra={"retry_after": 1},
        )
    return PostingOut.model_validate(row.response)


# --------------------------------------------------------------------------- cuentas


async def _resolve_accounts(session: AsyncSession, facts: Sequence[EntryFact]) -> list[LedgerAccount]:
    """Auto-crea las cuentas que falten y valida coherencia con las existentes."""
    resolved: list[LedgerAccount] = []
    for fact in facts:
        plan = plan_for_code(fact.account_code)
        await session.execute(
            pg_insert(LedgerAccount)
            .values(
                id=new_uuid7(),
                code=fact.account_code,
                name=f"{plan.name} ({fact.account_code})",
                type=plan.type,
                currency=fact.currency,
                owner_id=fact.owner_id,
                owner_type=fact.owner_type,
                is_control=plan.is_control,
                created_at=utcnow(),
            )
            .on_conflict_do_nothing(index_elements=["code"])
        )
        account = (
            await session.execute(select(LedgerAccount).where(LedgerAccount.code == fact.account_code))
        ).scalar_one()
        _assert_account_consistent(account, fact, plan)
        resolved.append(account)
    return resolved


def _assert_account_consistent(account: LedgerAccount, fact: EntryFact, plan: PlanAccount) -> None:
    if account.type != plan.type:
        raise ValidationError(
            f"la cuenta {fact.account_code!r} existe con tipo {account.type!r}; el plan exige {plan.type!r}"
        )
    if account.currency != fact.currency:
        raise ValidationError(
            f"la cuenta {fact.account_code!r} está en {account.currency!r}; el asiento usa {fact.currency!r}"
        )
    if plan.is_control:
        if account.owner_id != SYSTEM_OWNER_ID or account.owner_type != "system":
            raise ValidationError(f"la cuenta de control {fact.account_code!r} tiene un propietario inesperado")
    elif account.owner_id != fact.owner_id:
        raise ValidationError(f"la cuenta {fact.account_code!r} pertenece a otro owner_id")


# --------------------------------------------------------------------------- reversiones


async def _assert_reversal(
    session: AsyncSession,
    reverses_tx_id: uuid.UUID,
    entry_ids: Sequence[uuid.UUID | None],
) -> None:
    target = (
        await session.execute(select(LedgerTransaction.id).where(LedgerTransaction.id == reverses_tx_id))
    ).scalar_one_or_none()
    if target is None:
        raise ValidationError(f"reverses_tx_id {reverses_tx_id} no existe")

    already = (
        await session.execute(
            select(LedgerTransaction.id).where(
                LedgerTransaction.reverses_tx_id == reverses_tx_id,
                LedgerTransaction.type == "reversal",
            )
        )
    ).first()
    if already is not None:
        raise ConflictError("La transacción ya fue revertida")

    for entry_id in entry_ids:
        if entry_id is None:
            continue
        owner = (
            await session.execute(select(LedgerEntry.transaction_id).where(LedgerEntry.id == entry_id))
        ).scalar_one_or_none()
        if owner is None:
            raise ValidationError(f"reverses_entry_id {entry_id} no existe")
        if owner != reverses_tx_id:
            raise ValidationError(f"reverses_entry_id {entry_id} no pertenece a la transacción {reverses_tx_id}")


# --------------------------------------------------------------------------- defensa en profundidad


async def _assert_balanced_in_db(session: AsyncSession, transaction_id: uuid.UUID) -> None:
    """Llama a `ledger.assert_balanced` antes del COMMIT (L §2.2, ADR-0011 §1)."""
    await session.execute(
        text("SELECT ledger.ledger_assert_balanced(CAST(:tx_id AS uuid))"),
        {"tx_id": str(transaction_id)},
    )


# --------------------------------------------------------------------------- evento


async def _store_outbox_event(
    session: AsyncSession,
    *,
    transaction: LedgerTransaction,
    cmd: PostingsIn,
    entries: Sequence[ResolvedEntry],
) -> None:
    payload = build_ledger_posted_payload(
        transaction_id=transaction.id,
        tx_type=cmd.type,
        correlation_id=cmd.correlation_id,
        occurred_at=cmd.occurred_at,
        entries=entries,
    )
    event = build_event(
        event_type=EVENT_TYPE,
        schema_version=EVENT_SCHEMA_VERSION,
        aggregate_id=str(transaction.id),
        aggregate_type=AGGREGATE_TYPE,
        producer="ledger",
        payload=payload,
        correlation_id=str(cmd.correlation_id),
        causation_id=str(cmd.causation_id) if cmd.causation_id else None,
        timestamp=utcnow(),
    )
    session.add(
        OutboxEvent(
            id=event.event_id,
            event_type=event.event_type,
            schema_version=event.schema_version,
            aggregate_id=event.aggregate_id,
            aggregate_type=event.aggregate_type,
            payload=event.payload,
            correlation_id=event.correlation_id,
            causation_id=event.causation_id,
            producer=event.producer,
            created_at=event.timestamp,
        )
    )


# --------------------------------------------------------------------------- lectura


async def get_posting(session: AsyncSession, posting_id: uuid.UUID) -> PostingOut:
    """Recupera un posting por su `transaction_id` (Q-api-map §3)."""
    transaction = (
        await session.execute(select(LedgerTransaction).where(LedgerTransaction.id == posting_id))
    ).scalar_one_or_none()
    if transaction is None:
        raise NotFoundError("posting")

    rows = (
        await session.execute(
            select(LedgerEntry, LedgerAccount)
            .join(LedgerAccount, LedgerEntry.account_id == LedgerAccount.id)
            .where(LedgerEntry.transaction_id == transaction.id)
            .order_by(LedgerEntry.position)
        )
    ).all()
    resolved = [
        ResolvedEntry(
            entry_id=entry.id,
            position=entry.position,
            account_id=account.id,
            account_code=account.code,
            direction=entry.direction,
            amount=entry.amount,
            currency=entry.currency,
            reverses_entry_id=entry.reverses_entry_id,
        )
        for entry, account in rows
    ]
    return _build_posting(transaction, resolved, cast(TxType, transaction.type))


# --------------------------------------------------------------------------- presentación


def _build_posting(transaction: LedgerTransaction, entries: Sequence[ResolvedEntry], tx_type: TxType) -> PostingOut:
    return PostingOut(
        transaction_id=transaction.id,
        type=tx_type,
        correlation_id=transaction.correlation_id,
        causation_id=transaction.causation_id,
        occurred_at=transaction.occurred_at,
        reverses_tx_id=transaction.reverses_tx_id,
        metadata=transaction.tx_metadata,
        entries=[_entry_out(entry) for entry in entries],
        created_at=transaction.created_at,
    )


def _entry_out(entry: ResolvedEntry) -> EntryOut:
    return EntryOut(
        entry_id=entry.entry_id,
        position=entry.position,
        account_id=entry.account_id,
        account_code=entry.account_code,
        direction=cast(Literal["D", "C"], entry.direction),
        amount=canonical_amount(entry.amount),
        currency=entry.currency,
        reverses_entry_id=entry.reverses_entry_id,
    )
