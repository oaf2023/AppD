"""reconciler - comparación periódica wallet↔ledger (BUILD-019).

Compara la proyección `balances` contra `GET /internal/v1/balances` (todos los
propietarios), marca `stale`/`reconciled_at`, persiste `balance_snapshots` y
promueve `platform_wallet_reconcile_mismatches_total` con log de alerta.

No repara automáticamente: wallet es proyección, la reparación de una
proyección ausente/desfasada corresponde a investigación operativa (una
auto-sanación ocultaría la causa).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from decimal import Decimal

import httpx
from platform_kernel.clock import utcnow
from platform_kernel.security.tokens import new_service_token
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from wallet import metrics as wallet_metrics
from wallet.config import WalletSettings
from wallet.ledger_client import fetch_owner_balances
from wallet.models import Balance, BalanceSnapshot

logger = logging.getLogger("wallet.reconciler")


class Reconciler:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        settings: WalletSettings,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._settings = settings
        self._client = client
        self._task: asyncio.Task[None] | None = None
        self._stopped = asyncio.Event()

    async def start(self) -> None:
        self._stopped.clear()
        self._task = asyncio.create_task(self._run(), name="wallet-reconciler")

    async def stop(self) -> None:
        self._stopped.set()
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def _run(self) -> None:
        interval = max(1, self._settings.reconcile_interval_seconds)
        while not self._stopped.is_set():
            try:
                await self.run_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning(
                    "paso de reconciliación fallido; se reintentará",
                    extra={"extra_fields": {"service": "wallet"}},
                )
            try:
                await asyncio.wait_for(self._stopped.wait(), timeout=interval)
            except TimeoutError:
                continue

    async def run_once(self) -> int:
        """Una pasada; devuelve la cantidad de filas marcadas como stale."""
        settings = self._settings
        token = new_service_token(
            service_name=settings.service_name,
            secret=settings.service_token_secret,
            issuer=settings.jwt_issuer,
            audience=settings.service_token_audience,
        )
        ledger_rows, _as_of = await fetch_owner_balances(
            ledger_url=settings.ledger_url,
            token=token,
            owner_id=None,
            client=self._client,
            timeout=settings.ledger_timeout_seconds,
        )
        ledger_map = {(owner, currency): balance for owner, currency, balance in ledger_rows}
        now = utcnow()
        stale_count = 0
        async with self._session_factory() as session:
            balances = list((await session.execute(select(Balance))).scalars())
            seen: set[tuple[object, object]] = set()
            for row in balances:
                key = (row.user_id, row.currency)
                target = ledger_map.get(key)
                matched = target is not None and target == row.available
                row.stale = not matched
                row.reconciled_at = now
                session.add(
                    BalanceSnapshot(
                        user_id=row.user_id,
                        currency=row.currency,
                        wallet_balance=row.available,
                        ledger_balance=target if target is not None else Decimal(0),
                        matched=matched,
                    )
                )
                seen.add(key)
                if not matched:
                    stale_count += 1
                    wallet_metrics.WALLET_RECONCILE_MISMATCHES.inc()
                    logger.warning(
                        "descuadre wallet-ledger",
                        extra={
                            "extra_fields": {
                                "user_id": str(row.user_id),
                                "currency": row.currency,
                                "wallet_balance": str(row.available),
                                "ledger_balance": str(target) if target is not None else None,
                            }
                        },
                    )
            for key in set(ledger_map) - seen:
                # saldo en ledger sin fila en wallet: el proyector no llegó a aplicarlo
                stale_count += 1
                wallet_metrics.WALLET_RECONCILE_MISMATCHES.inc()
                logger.warning(
                    "saldo en ledger sin proyección en wallet",
                    extra={
                        "extra_fields": {
                            "user_id": str(key[0]),
                            "currency": str(key[1]),
                            "ledger_balance": str(ledger_map[key]),
                        }
                    },
                )
            await session.commit()
        return stale_count


__all__ = ["Reconciler"]
