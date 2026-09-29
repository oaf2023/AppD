"""breaker — cortacircuitos por proveedor, sin dependencias externas.

Semántica: `failure_threshold` fallos consecutivos → OPEN durante `cooldown_seconds`;
al expirar → HALF_OPEN (se permite una sonda); la sonda cierra (éxito) o reabre (fallo).
"""

from __future__ import annotations

import time
from collections.abc import Callable
from enum import StrEnum


class BreakerState(StrEnum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    def __init__(
        self,
        failure_threshold: int,
        cooldown_seconds: float,
        mono: Callable[[], float] = time.monotonic,
    ) -> None:
        if failure_threshold < 1:
            raise ValueError("failure_threshold debe ser >= 1")
        if cooldown_seconds <= 0:
            raise ValueError("cooldown_seconds debe ser > 0")
        self._threshold = failure_threshold
        self._cooldown = cooldown_seconds
        self._mono = mono
        self._failures = 0
        self._state = BreakerState.CLOSED
        self._opened_at = 0.0

    @property
    def state(self) -> BreakerState:
        if self._state == BreakerState.OPEN and self._mono() - self._opened_at >= self._cooldown:
            self._state = BreakerState.HALF_OPEN
        return self._state

    def available(self) -> bool:
        return self.state != BreakerState.OPEN

    def record_success(self) -> None:
        self._failures = 0
        self._state = BreakerState.CLOSED

    def record_failure(self) -> None:
        if self._state == BreakerState.HALF_OPEN:
            self._open()
            return
        self._failures += 1
        if self._failures >= self._threshold:
            self._open()

    def _open(self) -> None:
        self._state = BreakerState.OPEN
        self._opened_at = self._mono()
        self._failures = 0


__all__ = ["BreakerState", "CircuitBreaker"]
