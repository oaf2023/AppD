"""service - lógica del Wallet Service (Q-api-map §2.5, BUILD-019/021/022).

- `apply_ledger_posted`: aplica `LedgerPosted` a la proyección `balances` con
  deduplicación por `event_id` (P-event-catalog §3.3, at-least-once).
- `transfer`: A→B dentro de las cuentas propias; valida contra accounts (BOLA)
  y contra el saldo real en ledger; ejecuta un posting síncrono `transfer`.
- lecturas: balances y movimientos con cursor.

El saldo de transferencia se valida contra ledger (fuente de verdad, L §4.1);
`balances` es sólo proyección de lectura. La serialización A→B usa un lock por
usuario inyectado desde `main.py` (por proceso).
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import httpx
from platform_kernel.clock import utcnow
from platform_kernel.errors import AppError, ConflictError, NotFoundError, ValidationError
from platform_kernel.events import EventEnvelope
from platform_kernel.money import MoneyError, to_decimal
from platform_kernel.security.tokens import new_service_token
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from wallet import metrics as wallet_metrics
from wallet.accounts_client import fetch_account
from wallet.config import WalletSettings
from wallet.ledger_client import fetch_owner_balances, post_transfer_posting
from wallet.models import Balance, BalanceMovement, ProcessedEvent
from wallet.pagination import decode_cursor, encode_cursor
from wallet.schemas import TYPE_INSUFFICIENT, AccountRef, TransferIn

logger = logging.getLogger("wallet.service")

MAX_RANGE_DAYS = 90
MAX_PAGE_SIZE = 100
DEFAULT_PAGE_SIZE = 25


def client_account_code(currency: str, owner_id: uuid.UUID) -> str:
    """Código de la cuenta del usuario en ledger (L §7.1, espejo de ledger.consumer).

    El patrón de código no admite guiones: sufijo `u_<hex>` (ADR-0011 §1).
    Espejo intencional de `ledger.consumer.client_account_code`; el par se
    verifica en los tests de integración end-to-end.
    """
    return f"2000.PAYABLE.CLIENT.{currency}.u_{owner_id.hex}"


def _key_occurred_at(idempotency_key: str) -> datetime:
    """`occurred_at` determinista del uuid del Idempotency-Key (reintento idéntico).

    Sin esto, dos intentos con el mismo cuerpo producirían `occurred_at` distinto
    y ledger rechazaría el replay por `request_hash` (ADR-0010). uuid7: los 48
    bits altos son unix_ts_ms.
    """
    try:
        stamp_ms = uuid.UUID(idempotency_key).int >> 80
        # uuid7: 48 bits altos = unix_ts_ms; clamps defensivos (uuid4 → aleatorio)
        if stamp_ms < 1_577_836_800_000 or stamp_ms > 4_102_444_800_000:  # 2020-01-01..2100-01-01
            return utcnow()
        return datetime.fromtimestamp(stamp_ms / 1000, tz=UTC)
    except ValueError, OSError, OverflowError:
        return utcnow()


def _service_token(settings: WalletSettings) -> str:
    return new_service_token(
        service_name=settings.service_name,
        secret=settings.service_token_secret,
        issuer=settings.jwt_issuer,
        audience=settings.service_token_audience,
    )


def canonical_amount(value: Decimal) -> str:
    """Representación decimal canónica sin ceros a la derecha (ADR-0006).

    Espejo de `ledger.postings.canonical_amount` (las fronteras impiden imports
    cruzados; el par se verifica en los tests de integración).
    """
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


class WalletService:
    def __init__(
        self,
        session: AsyncSession,
        settings: WalletSettings,
        *,
        ledger_client: httpx.AsyncClient | None = None,
        accounts_client: httpx.AsyncClient | None = None,
    ) -> None:
        self.session = session
        self.settings = settings
        self._ledger_client = ledger_client
        self._accounts_client = accounts_client

    # ------------------------------------------------------------ proyección (consumidor)

    async def apply_ledger_posted(self, envelope: EventEnvelope) -> bool:
        """Aplica un `LedgerPosted` a `balances`/`balance_movements`.

        Devuelve False si el evento ya fue procesado o el payload es inválido
        (rollback + omisión: no bloquea el topic, at-least-once + deduplicación).
        """
        session = self.session
        try:
            if await session.get(ProcessedEvent, envelope.event_id) is not None:
                return False
            payload = envelope.payload
            entries = payload["entries"]
            if not isinstance(entries, list) or not entries:
                raise TypeError("entries ausente")
            occurred_at = datetime.fromisoformat(str(payload["occurred_at"]))
            if occurred_at.tzinfo is None:
                occurred_at = occurred_at.replace(tzinfo=UTC)
            tx_type = str(payload.get("type", "adjustment"))[:20]
            transaction_id = uuid.UUID(str(payload["transaction_id"]))
            rows: list[tuple[uuid.UUID, str, Decimal, str]] = []
            for entry in entries:
                if not isinstance(entry, dict):
                    raise TypeError("entry inválido")
                if entry.get("owner_type") != "user" or not entry.get("owner_id"):
                    continue
                owner_id = uuid.UUID(str(entry["owner_id"]))
                currency = str(entry["currency"])
                direction = str(entry["direction"])
                if direction not in ("D", "C"):
                    raise ValueError(f"dirección inválida: {direction}")
                amount = to_decimal(str(entry["amount"]))
                delta = amount if direction == "C" else -amount
                if delta == 0:
                    continue
                rows.append((owner_id, currency, delta, direction))
        except (KeyError, TypeError, ValueError, MoneyError) as exc:
            logger.error(
                "payload LedgerPosted inválido; se omite",
                extra={
                    "extra_fields": {
                        "event_id": envelope.event_id,
                        "event_type": envelope.event_type,
                        "error": str(exc)[:200],
                    }
                },
            )
            await session.rollback()
            return False

        for owner_id, currency, delta, direction in rows:
            await self._locked_balance(owner_id, currency, delta)
            session.add(
                BalanceMovement(
                    user_id=owner_id,
                    currency=currency,
                    delta=delta,
                    direction=direction,
                    tx_type=tx_type,
                    ledger_transaction_id=transaction_id,
                    occurred_at=occurred_at,
                )
            )
        session.add(ProcessedEvent(event_id=envelope.event_id, event_type=envelope.event_type, processed_at=utcnow()))
        await session.commit()
        return True

    async def _locked_balance(self, owner_id: uuid.UUID, currency: str, delta: Decimal) -> Balance:
        """Obtiene (creando si falta) la fila de balance y aplica el delta."""
        session = self.session
        row = await session.scalar(
            select(Balance).where(Balance.user_id == owner_id, Balance.currency == currency).with_for_update()
        )
        if row is None:
            row = Balance(user_id=owner_id, currency=currency, available=delta, reserved=Decimal(0))
            session.add(row)
        else:
            row.available = row.available + delta
            row.updated_at = utcnow()
        return row

    # ------------------------------------------------------------ lecturas

    async def list_balances(self, user_id: uuid.UUID) -> tuple[list[Balance], datetime, bool, datetime | None]:
        rows = list(
            (
                await self.session.execute(select(Balance).where(Balance.user_id == user_id).order_by(Balance.currency))
            ).scalars()
        )
        stale = any(row.stale for row in rows)
        checked_at = max((row.reconciled_at for row in rows if row.reconciled_at is not None), default=None)
        return rows, utcnow(), stale, checked_at

    async def get_balance(self, user_id: uuid.UUID, currency: str) -> Balance:
        row = await self.session.scalar(
            select(Balance).where(Balance.user_id == user_id, Balance.currency == currency.upper())
        )
        if row is None:
            raise NotFoundError("balance no encontrado")
        return row

    async def list_movements(
        self,
        *,
        user_id: uuid.UUID,
        from_ts: datetime,
        to_ts: datetime,
        cursor: str | None,
        limit: int,
    ) -> tuple[list[BalanceMovement], bool, str | None]:
        conditions = [
            BalanceMovement.user_id == user_id,
            BalanceMovement.occurred_at >= from_ts,
            BalanceMovement.occurred_at <= to_ts,
        ]
        if cursor:
            after_ts, after_id = decode_cursor(cursor)
            conditions.append(
                or_(
                    BalanceMovement.occurred_at < after_ts,
                    and_(BalanceMovement.occurred_at == after_ts, BalanceMovement.id < after_id),
                )
            )
        rows = list(
            (
                await self.session.execute(
                    select(BalanceMovement)
                    .where(*conditions)
                    .order_by(BalanceMovement.occurred_at.desc(), BalanceMovement.id.desc())
                    .limit(limit + 1)
                )
            ).scalars()
        )
        has_more = len(rows) > limit
        page = rows[:limit]
        next_cursor = encode_cursor(page[-1].occurred_at, page[-1].id) if has_more and page else None
        return page, has_more, next_cursor

    # ------------------------------------------------------------ transferencias (Q §2.5)

    async def transfer(
        self,
        *,
        user_id: uuid.UUID,
        body: TransferIn,
        idempotency_key: str,
        lock: asyncio.Lock | None = None,
    ) -> dict[str, Any]:
        try:
            amount = to_decimal(body.amount)
        except MoneyError as exc:
            raise ValidationError("amount debe ser un decimal válido") from exc
        if amount <= 0:
            raise ValidationError("amount debe ser mayor que cero")
        if body.from_account_id == body.to_account_id:
            raise ValidationError("origen y destino deben ser cuentas distintas")

        token = _service_token(self.settings)
        if lock is not None:
            await lock.acquire()
        try:
            return await self._transfer_locked(
                user_id=user_id,
                body=body,
                amount=amount,
                idempotency_key=idempotency_key,
                token=token,
            )
        finally:
            if lock is not None:
                lock.release()

    async def _transfer_locked(
        self,
        *,
        user_id: uuid.UUID,
        body: TransferIn,
        amount: Decimal,
        idempotency_key: str,
        token: str,
    ) -> dict[str, Any]:
        source = await fetch_account(
            accounts_url=self.settings.accounts_url,
            account_id=body.from_account_id,
            token=token,
            client=self._accounts_client,
            timeout=self.settings.accounts_timeout_seconds,
        )
        if source.user_id != user_id:
            # recurso ajeno o inexistente → misma respuesta 404 (§1.7.3, BOLA)
            raise NotFoundError("cuenta no encontrada")
        target = await fetch_account(
            accounts_url=self.settings.accounts_url,
            account_id=body.to_account_id,
            token=token,
            client=self._accounts_client,
            timeout=self.settings.accounts_timeout_seconds,
        )
        self._check_pair(source, target, body.currency)

        balances, _as_of = await fetch_owner_balances(
            ledger_url=self.settings.ledger_url,
            token=token,
            owner_id=user_id,
            client=self._ledger_client,
            timeout=self.settings.ledger_timeout_seconds,
        )
        available = next((bal for owner, curr, bal in balances if owner == user_id and curr == body.currency), None)
        if available is None or available < amount:
            raise AppError(
                409,
                TYPE_INSUFFICIENT,
                "Saldo insuficiente",
                f"saldo disponible {canonical_amount(available or Decimal(0))} {body.currency}",
            )

        occurred_at = _key_occurred_at(idempotency_key)
        entries = [
            {
                "account_code": client_account_code(body.currency, user_id),
                "direction": "D",
                "amount": canonical_amount(amount),
                "currency": body.currency,
                "owner_id": str(user_id),
                "owner_type": "user",
            },
            {
                "account_code": client_account_code(body.currency, target.user_id),
                "direction": "C",
                "amount": canonical_amount(amount),
                "currency": body.currency,
                "owner_id": str(target.user_id),
                "owner_type": "user",
            },
        ]
        transaction_id = await post_transfer_posting(
            ledger_url=self.settings.ledger_url,
            token=token,
            idempotency_key=idempotency_key,
            occurred_at=occurred_at,
            entries=entries,
            client=self._ledger_client,
            timeout=self.settings.ledger_timeout_seconds,
        )
        wallet_metrics.WALLET_TRANSFERS.inc()
        logger.info(
            "transferencia ejecutada",
            extra={
                "extra_fields": {
                    "transaction_id": str(transaction_id),
                    "user_id": str(user_id),
                    "currency": body.currency,
                }
            },
        )
        return {
            "transfer_id": transaction_id,
            "from_account_id": body.from_account_id,
            "to_account_id": body.to_account_id,
            "amount": canonical_amount(amount),
            "currency": body.currency,
            "status": "posted",
            "occurred_at": occurred_at.isoformat(),
        }

    @staticmethod
    def _check_pair(source: AccountRef, target: AccountRef, currency: str) -> None:
        if source.status != "active":
            raise ConflictError("la cuenta de origen debe estar activa")
        if target.status != "active":
            raise ConflictError("la cuenta de destino debe estar activa")
        if source.type != target.type:
            raise ConflictError("no se permiten transferencias entre modos de cuenta distintos")
        if source.currency != currency or target.currency != currency:
            raise ConflictError("la moneda debe coincidir con la de ambas cuentas")


def validate_range(from_ts: datetime, to_ts: datetime) -> None:
    """Ventana obligatoria ≤ 90 días (Q-api-map §2.6; reutilizado en §2.5)."""
    if to_ts <= from_ts:
        raise ValidationError("`to` debe ser posterior a `from`")
    if to_ts - from_ts > timedelta(days=MAX_RANGE_DAYS):
        raise ValidationError(f"rango máximo de {MAX_RANGE_DAYS} días")


__all__ = [
    "DEFAULT_PAGE_SIZE",
    "MAX_PAGE_SIZE",
    "MAX_RANGE_DAYS",
    "WalletService",
    "canonical_amount",
    "client_account_code",
    "validate_range",
]
