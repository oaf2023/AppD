"""conftest de pruebas de integración (ASGI en proceso, con lifespan real)."""

from __future__ import annotations

import pytest
from helpers import lifespan_client


@pytest.fixture
async def identity_client(clean_dbs: None):  # type: ignore[no-untyped-def]
    from identity.main import create_app

    async with lifespan_client(create_app()) as client:
        yield client


@pytest.fixture
async def audit_client(clean_dbs: None):  # type: ignore[no-untyped-def]
    from audit.main import create_app

    async with lifespan_client(create_app()) as client:
        yield client
