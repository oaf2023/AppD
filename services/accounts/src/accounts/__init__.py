"""accounts — servicio de cuentas de trading (Fase 2, BUILD-020/023).

Cuentas DEMO/LIVE separadas, auto-provisión DEMO desde `identity.user.registered`,
matriz de jurisdicciones con gating tipado y outbox transaccional de los eventos
`AccountCreated`/`DemoAccountCreated` (P-event-catalog #12/#16).
"""

from __future__ import annotations

__all__ = ["__version__"]

__version__ = "0.1.0"
