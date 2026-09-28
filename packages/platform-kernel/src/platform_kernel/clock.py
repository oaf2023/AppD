"""clock — reloj UTC canónico del sistema (fuente única para timestamps)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta


def utcnow() -> datetime:
    """Timestamp canónico en UTC con info de zona horaria."""
    return datetime.now(UTC)


def in_minutes(minutes: float) -> datetime:
    return utcnow() + timedelta(minutes=minutes)


def in_hours(hours: float) -> datetime:
    return utcnow() + timedelta(hours=hours)


def in_days(days: float) -> datetime:
    return utcnow() + timedelta(days=days)


__all__ = ["in_days", "in_hours", "in_minutes", "utcnow"]
