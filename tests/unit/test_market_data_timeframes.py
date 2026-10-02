"""Pruebas unitarias de buckets multi-timeframe (BUILD-030, K §4.4).

`bucket_start` es la función pura que gobierna la alineación UTC de todos los
timeframes; si cambia, cambian las velas de producción, así que sus fronteras
se fijan aquí (casos dorados).
"""

from __future__ import annotations

from datetime import UTC, datetime

from market_data.domain.models import TIMEFRAMES, Timeframe
from market_data.store import TIMEFRAME_DELTAS, bucket_start

H = lambda **kw: datetime(**kw, tzinfo=UTC)  # noqa: E731


def test_fronteras_de_bucket_por_timeframe() -> None:
    ts = H(year=2026, month=3, day=2, hour=10, minute=7, second=45, microsecond=123456)
    assert bucket_start(ts, "1m") == H(year=2026, month=3, day=2, hour=10, minute=7)
    assert bucket_start(ts, "5m") == H(year=2026, month=3, day=2, hour=10, minute=5)
    assert bucket_start(ts, "15m") == H(year=2026, month=3, day=2, hour=10, minute=0)
    assert bucket_start(ts, "1h") == H(year=2026, month=3, day=2, hour=10, minute=0)
    assert bucket_start(ts, "4h") == H(year=2026, month=3, day=2, hour=8, minute=0)
    assert bucket_start(ts, "1d") == H(year=2026, month=3, day=2, hour=0, minute=0)


def test_fronteras_criticas() -> None:
    # 5m: justo antes del múltiplo cae al bucket anterior
    before_5 = H(year=2026, month=3, day=2, hour=10, minute=4, second=59, microsecond=999999)
    assert bucket_start(before_5, "5m") == H(year=2026, month=3, day=2, hour=10, minute=0)
    assert bucket_start(before_5, "15m") == H(year=2026, month=3, day=2, hour=10, minute=0)
    before_15 = H(year=2026, month=3, day=2, hour=9, minute=59, second=59, microsecond=999999)
    assert bucket_start(before_15, "15m") == H(year=2026, month=3, day=2, hour=9, minute=45)
    # 4h alineado a 00/04/08/12/16/20 (época UTC, no local)
    assert bucket_start(H(year=2026, month=3, day=2, hour=4), "4h") == H(year=2026, month=3, day=2, hour=4)
    assert bucket_start(H(year=2026, month=3, day=2, hour=3, minute=59, second=59), "4h") == H(
        year=2026, month=3, day=2, hour=0
    )
    assert bucket_start(H(year=2026, month=3, day=2, hour=23, minute=59, second=59), "4h") == H(
        year=2026, month=3, day=2, hour=20
    )
    # 1d: medianoche UTC, el día cambia en UTC y no en la zona del cliente
    late = H(year=2026, month=3, day=2, hour=23, minute=59, second=59)
    assert bucket_start(late, "1d") == H(year=2026, month=3, day=2, hour=0)
    rollover = H(year=2026, month=3, day=3, hour=0, minute=0, second=1)
    assert bucket_start(rollover, "1d") == H(year=2026, month=3, day=3, hour=0)


def test_naive_se_trata_como_hora_de_pared() -> None:
    naive = datetime(2026, 3, 2, 10, 7, 45)
    assert bucket_start(naive, "5m") == datetime(2026, 3, 2, 10, 5)


def test_todos_los_timeframes_canonicos_tienen_delta_y_rango_de_bucket() -> None:
    ts = H(year=2026, month=3, day=2, hour=10, minute=7, second=45)
    for timeframe in TIMEFRAMES:
        bucket = bucket_start(ts, timeframe)
        assert bucket <= ts
        assert bucket + TIMEFRAME_DELTAS[timeframe] > ts
        # el bucket es idempotente: aplicarlo dos veces no lo mueve
        assert bucket_start(bucket, timeframe) == bucket


def test_jerarquia_de_buckets() -> None:
    """Un bucket de N siempre cae dentro de un bucket mayor o igual."""
    ts = H(year=2026, month=3, day=2, hour=10, minute=7, second=45)
    chain: list[Timeframe] = ["1m", "5m", "15m", "1h", "4h", "1d"]
    previous: datetime | None = None
    for timeframe in chain:
        bucket = bucket_start(ts, timeframe)
        if previous is not None:
            assert previous >= bucket  # 10:05 ⊂ 10:00 ⊂ 08:00 ⊂ día
        previous = bucket
