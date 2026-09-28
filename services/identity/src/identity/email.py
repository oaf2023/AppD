"""email — sink MOCK de correo (etiqueta MOCK: sin proveedor SMTP real).

`REQUIERE PROVEEDOR`: en Fase 1 los mensajes se persisten en `email_outbox`
para poder verificarlos en local/test sin enviar nada a terceros.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from identity.models import EmailOutbox


async def send_mock_email(
    session: AsyncSession,
    *,
    to_email: str,
    subject: str,
    body_text: str,
    template: str,
    meta: dict[str, Any] | None = None,
) -> EmailOutbox:
    record = EmailOutbox(
        to_email=to_email,
        subject=subject,
        body_text=body_text,
        template=template,
        meta=meta or {},
    )
    session.add(record)
    await session.flush()
    return record


__all__ = ["send_mock_email"]
